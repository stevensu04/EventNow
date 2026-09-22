from django.db import models
from django.contrib.auth.models import User

# 1. Core Event Model
class Event(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('full', 'Full'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ]
    CATEGORY_CHOICES = [
        ('tech', 'Tech'),
        ('business', 'Business'),
        ('food', 'Food & Drink'),
        ('music', 'Music & Arts'),
        ('community', 'Community'),
    ]
    organizer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    title = models.CharField(max_length=200)
    description = models.TextField()
    location = models.CharField(max_length=200)
    date = models.DateField() # Single-day event focus
    capacity = models.IntegerField(default=50)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='community')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    is_deleted = models.BooleanField(default=False) # soft delete to prevent data getting lost(preserve historical data)
    
    def __str__(self):
        return self.title

    def is_managed_by(self, user):
        """Organizers manage their own events; superusers manage everything."""
        return user.is_authenticated and (user.is_superuser or self.organizer_id == user.id)

# 2. Session Model: Representing parallel tracks within an event
class Session(models.Model):
    # Foreign Key: Many-to-One relationship linking sessions to a specific event
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='sessions')
    title = models.CharField(max_length=200)
    speaker = models.CharField(max_length=200)
    start_time = models.TimeField()
    end_time = models.TimeField()
    track = models.CharField(max_length=100) # For identifying parallel streams
    max_capacity = models.IntegerField(default=50)
    
    def __str__(self):
        return f"{self.title} ({self.start_time})"

# 3. Attendee Model: Handling registration data
class Attendee(models.Model):
    full_name = models.CharField(max_length=100)
    email = models.EmailField()

    # Explicit Foreign Key for clear event attribution and easier querying
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='attendees')

    # Many-to-Many: Allows an attendee to register for multiple sessions (parallel tracks)
    selected_sessions = models.ManyToManyField(Session, blank=True, related_name='attendees')

    registration_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='confirmed')

    def __str__(self):
        # Displays attendee name and associated event title for clarity in Admin UI
        return f"{self.full_name} - {self.event.title}"

# 4. Notification Model: System Notifications for Dashboard   
class Notification(models.Model):
    title = models.CharField(max_length=255)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

# 5. Subscription Model: SaaS Subscription System     
class Subscription(models.Model):
    PLAN_CHOICES = [
        ('free', 'Free'),
        ('pro', 'Professional'),
        ('ent', 'Enterprise'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='subscription')
    plan = models.CharField(max_length=10, choices=PLAN_CHOICES, default='free')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.get_plan_display()}"

    # Only Pro or Enterprise Users can create events
    @property
    def can_create_event(self):
        return self.plan in ['pro', 'ent']


# 6. AIUsage Model: per-user daily counter that caps paid OpenAI calls
class AIUsage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_usage')
    day = models.DateField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'day'], name='unique_ai_usage_per_day')]
