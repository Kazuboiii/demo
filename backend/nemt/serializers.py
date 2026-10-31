from rest_framework import serializers

from .models import RideCostEstimate, TransportRequest, Trip


class TransportRequestSerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    created_by_name = serializers.ReadOnlyField(source="created_by.email", default=None)

    class Meta:
        model = TransportRequest
        fields = [
            "id", "reference", "business_unit", "business_unit_name", "patient_name",
            "pickup_location", "dropoff_location", "pickup_time", "status",
            "created_by", "created_by_name", "assigned_driver", "assigned_vehicle",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at"]

    def validate(self, attrs):
        user = self.context["request"].user
        bu = attrs.get("business_unit") or getattr(self.instance, "business_unit", None)
        if bu is not None and not user.can_access_business_unit(bu):
            raise serializers.ValidationError("Not authorized for this business unit.")
        return attrs


class TripSerializer(serializers.ModelSerializer):
    request_reference = serializers.ReadOnlyField(source="request.reference")
    driver_name = serializers.ReadOnlyField(source="driver.user.email", default=None)
    vehicle_plate = serializers.ReadOnlyField(source="vehicle.license_plate")

    def validate(self, attrs):
        req = attrs.get("request", getattr(self.instance, "request", None))
        vehicle = attrs.get("vehicle", getattr(self.instance, "vehicle", None))
        driver = attrs.get("driver", getattr(self.instance, "driver", None))
        if not self.context["request"].user.can_access_business_unit(req.business_unit):
            raise serializers.ValidationError("Not authorized for this business unit.")
        if vehicle.business_unit_id != req.business_unit_id or driver.user.business_unit_id != req.business_unit_id:
            raise serializers.ValidationError("Driver, vehicle, and request must belong to the same business unit.")
        if not self.instance and (req.status != "pending" or vehicle.status != "available" or not driver.is_available):
            raise serializers.ValidationError("Request, driver, or vehicle is unavailable.")
        return attrs

    class Meta:
        model = Trip
        fields = [
            "id", "request", "request_reference", "driver", "driver_name",
            "vehicle", "vehicle_plate", "status", "start_time", "pickup_time",
            "dropoff_time", "end_time", "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class RideCostEstimateSerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    request_reference = serializers.ReadOnlyField(
        source="transport_request.reference", default=None
    )
    trip_reference = serializers.ReadOnlyField(
        source="trip.request.reference", default=None
    )

    class Meta:
        model = RideCostEstimate
        fields = [
            "id", "reference", "business_unit", "business_unit_name",
            "transport_request", "request_reference", "trip", "trip_reference",
            "distance_km", "duration_minutes", "base_fee", "per_km_rate",
            "driver_hourly_rate", "tolls", "total_cost", "currency", "notes",
            "created_by", "created_at",
        ]
        read_only_fields = ["total_cost", "created_by", "created_at"]

    def validate(self, attrs):
        user = self.context["request"].user
        bu = attrs.get("business_unit") or getattr(self.instance, "business_unit", None)
        if bu is not None and not user.can_access_business_unit(bu):
            raise serializers.ValidationError("Not authorized for this business unit.")
        request_obj = attrs.get("transport_request", getattr(self.instance, "transport_request", None))
        if request_obj is not None and bu is not None and request_obj.business_unit_id != bu.pk:
            raise serializers.ValidationError(
                "The transport request must belong to the same division."
            )
        trip = attrs.get("trip", getattr(self.instance, "trip", None))
        if trip is not None and bu is not None and trip.request.business_unit_id != bu.pk:
            raise serializers.ValidationError("The trip must belong to the same division.")
        return attrs
