from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Sum
from django.views.decorators.http import require_POST
from .models import (Address,)
from .forms import AddressForm
from payment.services.payment_services import (CheckoutServices)
from cart.services.cart_services import get_user_cart
import os
from django.urls import reverse
from urllib.parse import urlencode
from shop.recommendations import record_cart_interest
from .models import Order, OrderItem, ReturnRequest

# Create your views here.
def checkout(request):
    cart_items, cart_total = get_user_cart(request)
    if not cart_items:
        messages.error(request, 'Cart is empty')
        return redirect('cart')

    # Treat starting checkout as a strong intent signal (watchlist-ish behavior).
    record_cart_interest(request.user, weight=2)
        
    if request.method == 'POST':
        form = AddressForm(request.POST)
        if form.is_valid():
            terms_accepted = form.cleaned_data.get('terms_accepted')
            if terms_accepted:
                checkout_services = CheckoutServices()
                success, message = checkout_services.handle_payment_method(request, form)
                if success:
                    # If Stripe, redirect to Stripe checkout page (session URL)
                    if form.cleaned_data.get('method') == 'STRIPE':
                        return redirect(message)  # message contains Stripe session URL

                    if form.cleaned_data.get('method') == 'COD':
                        query = urlencode({'order_number': message})
                        return redirect(f"{reverse('order_success')}?{query}")

                    messages.success(request, message)
                    return redirect('cart')
                else:
                    messages.error(request, message)
                    return redirect('checkout')
                
    else:
        form = AddressForm()
    context={
        'form':form,
        'button': 'Submit',
        'cart_items': cart_items,
        'cart_total': cart_total,
        'stripe_publishable_key': os.getenv('STRIPE_PUBLISHABLE_KEY', ''),
    }
    return render(request, 'payment/checkout.html', context)

def shop_cancel(request):
    # If user cancels payment, still record intent for better recommendations.
    record_cart_interest(request.user, weight=2)
    return render(request, 'payment/cancel.html')

def success(request):
    checkout_services = CheckoutServices()
    success, message = checkout_services.stripe_payment_success(request)
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)
        
    return render(request, 'payment/success.html')


def order_success(request):
    order_number = request.GET.get('order_number')
    return render(request, 'payment/order_success.html', {'order_number': order_number})


@login_required(login_url="login")
def my_orders(request):
    orders_qs = (
        Order.objects.filter(user=request.user)
        .select_related("payment", "address")
        .prefetch_related("items", "items__product")
        .annotate(total_qty=Sum("items__quantity"))
        .order_by("-created_at")
    )
    paginator = Paginator(orders_qs, 10)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "payment/my_orders.html", {"page_obj": page_obj})


@login_required(login_url="login")
def order_details(request, pk):
    order = (
        Order.objects.filter(order_uuid=pk, user=request.user)
        .select_related("payment", "address")
        .prefetch_related("items", "items__product")
        .first()
    )
    if not order:
        messages.error(request, "Order not found.")
        return redirect("my_orders")
    return render(request, "payment/order_details.html", {"order": order})


@login_required(login_url="login")
@require_POST
def order_cancel(request, pk):
    order = Order.objects.filter(order_uuid=pk, user=request.user).only("id", "order_uuid", "order_number", "status").first()
    if not order:
        messages.error(request, "Order not found.")
        return redirect("my_orders")
    if order.status not in {"PENDING", "PROCESSING"}:
        messages.error(request, f"Order {order.order_number} cannot be cancelled (status: {order.status}).")
        return redirect("my_orders")
    order.status = "CANCELLED"
    order.save(update_fields=["status", "updated_at"])
    messages.success(request, f"Cancelled {order.order_number}.")
    return redirect("my_orders")


@login_required(login_url="login")
@require_POST
def order_refund_request(request, pk):
    order = (
        Order.objects.filter(order_uuid=pk, user=request.user)
        .select_related("payment")
        .prefetch_related("items", "items__product")
        .first()
    )
    if not order:
        messages.error(request, "Order not found.")
        return redirect("my_orders")

    if order.status in {"PENDING", "PROCESSING"}:
        messages.error(request, "This order is not shipped yet. Consider cancelling the order instead.")
        return redirect("my_orders")
    if order.status == "CANCELLED":
        messages.error(request, "This order is already cancelled.")
        return redirect("my_orders")
    if order.status == "SHIPPED":
        messages.error(request, "This order is shipped. You can request a return/refund after delivery.")
        return redirect("my_orders")

    if order.status not in {"COMPLETED", "RETURNED"}:
        messages.error(request, f"Refund is not available for status: {order.status}.")
        return redirect("my_orders")

    created_any = False
    for item in list(order.items.all()):
        exists = ReturnRequest.objects.filter(order_item=item).exclude(status__in={"REJECTED"}).exists()
        if exists:
            continue
        ReturnRequest.objects.create(
            order_item=item,
            reason="User requested refund/return from My Orders",
            status="REQUESTED",
        )
        created_any = True

    if created_any:
        messages.success(request, f"Refund/return request submitted for {order.order_number}.")
    else:
        messages.info(request, f"A refund/return request already exists for {order.order_number}.")
    return redirect("my_orders")
