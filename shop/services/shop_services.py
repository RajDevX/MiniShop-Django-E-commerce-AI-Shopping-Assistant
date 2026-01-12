from django.core.paginator import Paginator
from decimal import Decimal, InvalidOperation
from dashboard.models import Product

class ShopServices:
    def get_category_products(self, request, slug):
        try:
            product = Product.objects.filter(category__slug=slug).prefetch_related('category').order_by('-id')
            min_price = (request.GET.get("min_price") or "").strip()
            max_price = (request.GET.get("max_price") or "").strip()
            if min_price:
                try:
                    product = product.filter(price__gte=Decimal(min_price))
                except (InvalidOperation, ValueError):
                    pass
            if max_price:
                try:
                    product = product.filter(price__lte=Decimal(max_price))
                except (InvalidOperation, ValueError):
                    pass
            paginator = Paginator(product, 10)
            page_number = request.GET.get('page')
            products = paginator.get_page(page_number)
            return True, 'Products Listed', products
        except Exception as e:
            return False, f"An error occurred: {e}", None
