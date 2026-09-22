from rest_framework import serializers
from .models import Attendee, Notification

# 1. Serializer for Attendee model to handle API requests
class AttendeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendee
        fields = '__all__' # or designate specific column like ['id', 'full_name', 'email', 'status']

# 2. Serializer for system notifications
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        # Designating specific fields for better data control and security
        fields = ['id', 'title', 'message', 'timestamp']