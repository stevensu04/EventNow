from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Event, Session, Attendee, Subscription

# 1. Inline interface for Subscription management within the User page
class SubscriptionInline(admin.StackedInline):
    model = Subscription
    can_delete = False
    verbose_name_plural = 'Subscription Management'
    fk_name = 'user' # Link to User model

# 2. Customising UserAdmin to display SaaS-related information
class UserAdmin(BaseUserAdmin):
    # Add Subscription fields as an 'Inline' section in User profile
    inlines = (SubscriptionInline, )

    # Add custom columns to the user list view
    list_display = BaseUserAdmin.list_display + ('get_plan',)

    # Helper method to safely retrieve and display the user's current plan
    def get_plan(self, obj):
        try:
            return obj.subscription.get_plan_display()
        except Subscription.DoesNotExist:
            return "No Plan"
    get_plan.short_description = 'Subscription Plan'

# Re-register User model with our custom UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# 3. Registration for Event model with basic list sorting and search
@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'date', 'location', 'category', 'status', 'capacity', 'organizer', 'is_deleted')
    list_filter = ('status', 'category', 'is_deleted')
    search_fields = ('title', 'location')

# 4. Registration for Session model with hierarchical filtering
@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('title', 'event', 'speaker', 'start_time')
    list_filter = ('event',) # Filter sessions by their parent event

# 5. Registration for Attendee model with advanced Many-to-Many editing
@admin.register(Attendee)
class AttendeeAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'event', 'registration_date')
    # Filter attendees by events or specific sessions
    list_filter = ('event', 'selected_sessions')
    # Provides an intuitive UI for managing Many-to-Many session selection
    filter_horizontal = ('selected_sessions',)