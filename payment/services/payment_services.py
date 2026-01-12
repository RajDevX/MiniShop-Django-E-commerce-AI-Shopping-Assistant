from django.db import transaction
from payment.models import (Address, Payment, Order, OrderItem, Refund, ReturnRequest)
from dashboard.models import Product
from django.contrib.auth.models import User
from payment.forms import AddressForm
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from django.utils.crypto import get_random_string
from django.contrib.auth import login
import uuid
import os
import json
import stripe
from cart.models import CartItem
from cart.services.cart_services import get_user_cart
from decimal import Decimal, ROUND_HALF_UP
import logging

logger = logging.getLogger(__name__)

class CheckoutServices:

    def _create_order_items_and_clear_cart(self, request, order):
        used_db_cart = False
        if request.user.is_authenticated:
            db_cart_items = CartItem.objects.filter(user=request.user).select_related('product')
            if db_cart_items.exists():
                used_db_cart = True
                for cart_item in db_cart_items:
                    OrderItem.objects.create(
                        order=order,
                        product=cart_item.product,
                        quantity=cart_item.quantity,
                        price=cart_item.product_price,
                    )
                db_cart_items.delete()

        if not used_db_cart:
            cart = request.session.get('cart') or {}
            for _item_id, item in cart.items():
                try:
                    product = Product.objects.get(id=item['id'])
                except Product.DoesNotExist:
                    raise Product.DoesNotExist(f"Product does not exist. Product ID: {item['id']}")
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=int(item['quantity']),
                    price=Decimal(str(item['price'])),
                )
            request.session.pop('cart', None)  # Remove cart from session
            request.session.modified = True  # Mark session as changed for saving

    def _cod(self, request, address_id):
        cart_items, cart_total = get_user_cart(request)
        if not cart_items:
            return False, 'Cart is empty'

        total_amount = Decimal(str(cart_total))
        tax_cents = int(os.getenv('CHECKOUT_TAX_CENTS', '0') or 0)
        service_cents = int(os.getenv('CHECKOUT_SERVICE_CENTS', '0') or 0)
        if tax_cents:
            total_amount += (Decimal(tax_cents) / 100)
        if service_cents:
            total_amount += (Decimal(service_cents) / 100)

        try:
            with transaction.atomic():
                address = Address.objects.select_for_update().filter(id=address_id).first()
                if not address:
                    return False, "Address not found"

                address.payment_draft = 'APPROVED'
                address.save()

                payment = Payment.objects.create(
                    transaction_id=f"cod_{uuid.uuid4().hex}",
                    amount=total_amount,
                    is_paid=False,
                    paid_at=None,
                )

                user = request.user if request.user.is_authenticated else None
                order = Order.objects.create(
                    user=user,
                    payment=payment,
                    address=address,
                    total_price=total_amount,
                    status='PROCESSING',
                )

                self._create_order_items_and_clear_cart(request, order)

            return True, order.order_number
        except Product.DoesNotExist as e:
            return False, str(e)
        except Exception as e:
            return False, f"An error occurred: {str(e)}"
        
    def handle_payment_method(self, request, form):
        """
        Handles payment method selection. 
        Adds address to database
        Returns: bool, str
        """
        try:
            ## Check if form is valid
            if form.is_valid():
                account = False
                ## Check if terms and conditions are accepted
                if not form.cleaned_data.get('terms_accepted'):
                    return False, 'Please accept the terms and conditions.'
                ## Check if account creation is enabled
                account_create = form.cleaned_data.get('account_create')
                if account_create:
                    account= True
                    return False, 'Account creation not implemented yet.'
                ## Save address to database
                address =form.save(commit=False)
                if request.user.is_authenticated:
                    address.user = request.user
                address.save()
                ## Get address ID
                address_id = address.id
                ## Get payment method
                payment_method = form.cleaned_data.get('method')
                ## Match payment method
                match payment_method:
                    case 'COD':
                        return self._cod(request, address_id)
                    case 'STRIPE':
                        return self._stripe(request, address_id,account)
                    case 'PAYPAL':
                        return False, 'PayPal not implemented yet'
                    case 'CREDIT_CARD':
                        return False, 'Credit Card not implemented yet'
                    case _:
                            return False, 'Invalid Payment Method'
        except Exception as e:
            return False, f"An error occurred: {str(e)}"

    def _stripe(self, request, address_id, account):
        """
        Stripe payment handling logic
        Create Checkout Session from cart
        Includes: Tax and Service Charges
        Returns: bool, str
        Payment Checkout: Success URL and Cancel URL
        """
        SECRET_KEY = os.getenv('STRIPE_SECRET_KEY') ## Stripe Secret Key
        
        try:
            ## Check if Stripe Secret Key is set
            if SECRET_KEY:
                ## Set Stripe API Key
                stripe.api_key = SECRET_KEY
                cart_items, _cart_total = get_user_cart(request)
                if not cart_items:
                    return False, 'Cart is empty'
                ## Create line items
                line_items = []
                ## Iterate over cart items
                for cart_item in cart_items:
                    try: ## Check if product exists
                        product = Product.objects.get(id=cart_item['id'])
                    except Product.DoesNotExist:
                        return False, f"Product does not exist. Product ID: {cart_item['id']}"
                    
                    unit_amount = int(
                        (Decimal(str(cart_item['price'])) * 100).quantize(
                            Decimal("1"), rounding=ROUND_HALF_UP
                        )
                    )
                    line_items.append({ ## Adding item to line_items
                        'price_data': {
                            'currency': 'usd',
                            'unit_amount': unit_amount,## Stripe use cents ,Convert price to cents
                            'product_data': {
                                'name': product.name,
                            },
                        },
                        'quantity': int(cart_item['quantity']),
                    })
                tax_cents = int(os.getenv('CHECKOUT_TAX_CENTS', '0') or 0)
                if tax_cents > 0:
                    line_items.append({
                        'price_data': {
                            'currency': 'usd',
                            'unit_amount': tax_cents,
                            'product_data': {'name': "Tax"},
                        },
                        'quantity': 1,
                    })
                service_cents = int(os.getenv('CHECKOUT_SERVICE_CENTS', '0') or 0)
                if service_cents > 0:
                    line_items.append({
                        'price_data': {
                            'currency': 'usd',
                            'unit_amount': service_cents,
                            'product_data': {'name': "Service Charges"},
                        },
                        'quantity': 1,
                    })
                ## Get Domain from env
                domain = os.getenv('DOMAIN')
                ## Check if domain is set
                if not domain:
                    if settings.DEBUG:## If DEBUG is True, use localhost
                        domain = 'http://127.0.0.1:8000'
                    else: ## If DEBUG is False, Show the error message
                        return False, 'Domain is not set'
                ## Append domain to success and cancel URLs
                success_url = f"{domain}/payment/success/?session_id={{CHECKOUT_SESSION_ID}}"
                cancel_url = f"{domain}/payment/cancel/?session_id={{CHECKOUT_SESSION_ID}}"
                ## Create Stripe Checkout Session
                session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=line_items,
                    mode='payment',
                    success_url=success_url,
                    cancel_url=cancel_url,
                    metadata={
                        'address_id': str(address_id),
                        'account': str(account),
                    },
                )
                return True, session.url
                
            else:
                return False, 'Invalid Secret Key'
        except Exception as e:
            logger.exception("Stripe checkout session creation failed")
            return False, f"An error occurred: {str(e)}"
    
    def stripe_payment_success(self, request):
        ## Get Session ID from request
        session_id = request.GET.get('session_id')
        if session_id:## If Session ID is not None
            try:
                SECRET_KEY = os.getenv('STRIPE_SECRET_KEY') ## Stripe Secret Key
                stripe.api_key = SECRET_KEY ## Add Stripe Secret Key to Stripe API
                ## Retrieve Stripe Checkout Session from Session ID
                session = stripe.checkout.Session.retrieve(session_id)
                ## Check if session is paid
                if session.payment_status == 'paid':
                    address_id = int(session.metadata['address_id'])
                    ## Add data to database
                    return self._adding_data_to_database(request, address_id, session)
                    
                else:
                    return False, f"Payment Not Completed: {session.payment_status}"
            except stripe.error.StripeError as e:
                logger.exception("StripeError during payment success retrieval")
                return False, f"StripeError: {str(e)}"
            except Exception as e:
                logger.exception("Payment success handling failed")
                return False, f"An error occurred: {str(e)}"
        else:
            return False, "Session_id not found"
    
    def _adding_data_to_database(self, request, address_id, session):
        """
        Updates payment_draft to APPROVED
        Creates Payment, Order and OrderItem
        Returns: bool, str
        """
        try:
            with transaction.atomic():
                """
                Create User if account creation is enabled
                transaction.atomic() is used to make sure that the 
                database is updated only once. If an error occurs,
                the database will not be updated.
                """
                ## Get Amount from session, divide by 100 to get amount.
                amount = session.amount_total/100
                account = session.metadata['account']
                if not request.user.is_authenticated:
                    if account:
                        try:
                            ## Create User
                            email = f"user_{address_id}@example.com"
                            user = User.objects.filter(email=email).first()
                            if not user:
                                username = f"user_{address_id}_{uuid.uuid4().hex[:6]}"
                                raw_password = get_random_string(10)  # Agar zaroor ho show/send kar do
                                user = User.objects.create_user(
                                    username=username,
                                    email=email,
                                    password=raw_password,
                                )
                            login(request, user)
                        except Exception as e:
                            return False, f"An error occurred: {str(e)}"
                ## Get Address from database
                address=Address.objects.filter(id=address_id).first()
                if request.user.is_authenticated and address and not address.user_id:
                    address.user = request.user
                ## Check if payment draft is not approved
                if not address.payment_draft=='APPROVED':
                    ## Update payment_draft to APPROVED
                    address.payment_draft='APPROVED'
                    ## Save Address to database
                    address.save()
                ## Create Payment
                payment,created_payment = Payment.objects.get_or_create(
                    transaction_id=session.payment_intent,
                    amount=amount,
                    paid_at= timezone.now(),
                    is_paid=True,
                )
                payment.save()
                ## Get User
                user= request.user if request.user.is_authenticated else None
                ## Create Order
                order,created_order = Order.objects.get_or_create(
                    user = user,
                    payment=payment,
                    address=address,
                    total_price=amount,
                    status='PROCESSING',
                )
                order.save()
                ## Check if order is created
                if created_order:
                    self._create_order_items_and_clear_cart(request, order)
                    
            return True, f"Payment Successful. Order ID: {order.order_number}"
        except Exception as e:
            logger.exception("Order/payment DB write failed")
            return False, f"An error occurred: {str(e)}"


            
            
            
            
                
        
