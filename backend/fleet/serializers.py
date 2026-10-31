from rest_framework import serializers

from .models import DriverProfile, GPSPosition, TrackingDevice, Vehicle, VehicleAssignment


class VehicleSerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")

    class Meta:
        model = Vehicle
        fields = [
            "id", "license_plate", "business_unit", "business_unit_name", "make",
            "model", "year", "capacity", "status", "maintenance_note", "created_at",
        ]


class DriverProfileSerializer(serializers.ModelSerializer):
    user_email = serializers.ReadOnlyField(source="user.email")
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = DriverProfile
        fields = ["id", "user", "user_email", "user_name", "license_number",
                  "phone", "is_available", "created_at"]

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.email


class VehicleAssignmentSerializer(serializers.ModelSerializer):
    vehicle_plate = serializers.ReadOnlyField(source="vehicle.license_plate")
    driver_name = serializers.ReadOnlyField(source="driver.user.email")
    is_active = serializers.ReadOnlyField()

    def validate(self, attrs):
        vehicle = attrs.get("vehicle", getattr(self.instance, "vehicle", None))
        driver = attrs.get("driver", getattr(self.instance, "driver", None))
        if not self.context["request"].user.can_access_business_unit(vehicle.business_unit):
            raise serializers.ValidationError("Not authorized for this vehicle.")
        if driver.user.business_unit_id != vehicle.business_unit_id:
            raise serializers.ValidationError("Driver and vehicle must belong to the same business unit.")
        if not self.instance and (vehicle.status != "available" or not driver.is_available):
            raise serializers.ValidationError("Driver or vehicle is unavailable.")
        return attrs

    class Meta:
        model = VehicleAssignment
        fields = ["id", "vehicle", "vehicle_plate", "driver", "driver_name",
                  "assigned_at", "returned_at", "note", "is_active"]


class TrackingDeviceSerializer(serializers.ModelSerializer):
    vehicle_plate = serializers.ReadOnlyField(source="vehicle.license_plate")

    class Meta:
        model = TrackingDevice
        fields = ["id", "device_id", "vehicle", "vehicle_plate",
                  "is_connected", "last_seen"]


class GPSPositionSerializer(serializers.ModelSerializer):
    vehicle_plate = serializers.ReadOnlyField(source="vehicle.license_plate")

    class Meta:
        model = GPSPosition
        fields = [
            "id", "vehicle", "vehicle_plate", "latitude", "longitude",
            "recorded_at", "simulated", "speed", "trip",
        ]
