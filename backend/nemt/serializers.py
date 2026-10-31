from rest_framework import serializers

from .models import (
    RideAssignment,
    RideFareEstimate,
    RideRecord,
    RideRequest,
    RideCostEstimate,
    TransportRequest,
    Trip,
    VehicleMaintenanceRecord,
    TransportationExpense,
)


class TransportRequestSerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    created_by_name = serializers.ReadOnlyField(source="created_by.email", default=None)

    class Meta:
        model = TransportRequest
        fields = [
            "id", "reference", "business_unit", "business_unit_name", "passenger_name",
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


class RideRequestSerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    created_by_name = serializers.ReadOnlyField(source="created_by.email", default=None)
    driver_name = serializers.ReadOnlyField(source="assigned_driver.user.email", default=None)
    vehicle_plate = serializers.ReadOnlyField(source="assigned_vehicle.license_plate", default=None)

    class Meta:
        model = RideRequest
        fields = [
            "id", "reference", "business_unit", "business_unit_name", "rider_name",
            "pickup_location", "dropoff_location", "requested_at", "scheduled_at",
            "status", "created_by", "created_by_name", "assigned_driver", "driver_name",
            "assigned_vehicle", "vehicle_plate", "ride_trip", "notes",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at"]

    def validate(self, attrs):
        user = self.context["request"].user
        bu = attrs.get("business_unit") or getattr(self.instance, "business_unit", None)
        if bu is not None and not user.can_access_business_unit(bu):
            raise serializers.ValidationError("Not authorized for this business unit.")
        driver = attrs.get("assigned_driver", getattr(self.instance, "assigned_driver", None))
        if driver is not None and bu is not None and driver.user.business_unit_id != bu.pk:
            raise serializers.ValidationError("Assigned driver must belong to the same business unit.")
        vehicle = attrs.get("assigned_vehicle", getattr(self.instance, "assigned_vehicle", None))
        if vehicle is not None and bu is not None and vehicle.business_unit_id != bu.pk:
            raise serializers.ValidationError("Assigned vehicle must belong to the same business unit.")
        return attrs


class RideAssignmentSerializer(serializers.ModelSerializer):
    ride_reference = serializers.ReadOnlyField(source="ride_request.reference")
    driver_name = serializers.ReadOnlyField(source="driver.user.email")
    vehicle_plate = serializers.ReadOnlyField(source="vehicle.license_plate")

    class Meta:
        model = RideAssignment
        fields = [
            "id", "ride_request", "ride_reference", "driver", "driver_name",
            "vehicle", "vehicle_plate", "assigned_at", "accepted_at", "notes",
        ]
        read_only_fields = ["assigned_at"]

    def validate(self, attrs):
        user = self.context["request"].user
        ride_request = attrs.get("ride_request", getattr(self.instance, "ride_request", None))
        if ride_request is not None and not user.can_access_business_unit(ride_request.business_unit):
            raise serializers.ValidationError("Not authorized for this ride request.")
        driver = attrs.get("driver", getattr(self.instance, "driver", None))
        if driver is not None and ride_request is not None and driver.user.business_unit_id != ride_request.business_unit_id:
            raise serializers.ValidationError("Driver must belong to the same business unit as the ride request.")
        vehicle = attrs.get("vehicle", getattr(self.instance, "vehicle", None))
        if vehicle is not None and ride_request is not None and vehicle.business_unit_id != ride_request.business_unit_id:
            raise serializers.ValidationError("Vehicle must belong to the same business unit as the ride request.")
        return attrs


class RideRecordSerializer(serializers.ModelSerializer):
    ride_reference = serializers.ReadOnlyField(source="ride_request.reference")
    driver_name = serializers.ReadOnlyField(source="driver.user.email")
    vehicle_plate = serializers.ReadOnlyField(source="vehicle.license_plate")
    business_unit_name = serializers.ReadOnlyField(source="ride_request.business_unit.name")

    class Meta:
        model = RideRecord
        fields = [
            "id", "ride_request", "ride_reference", "driver", "driver_name",
            "vehicle", "vehicle_plate", "status", "pickup_time", "dropoff_time",
            "completed_at", "notes", "business_unit_name", "created_at",
        ]
        read_only_fields = ["created_at"]


class RideFareEstimateSerializer(serializers.ModelSerializer):
    business_unit_name = serializers.ReadOnlyField(source="business_unit.name")
    ride_reference = serializers.ReadOnlyField(source="ride_request.reference", default=None)
    trip_reference = serializers.ReadOnlyField(source="trip.request.reference", default=None)

    class Meta:
        model = RideFareEstimate
        fields = [
            "id", "reference", "business_unit", "business_unit_name",
            "ride_request", "ride_reference", "trip", "trip_reference",
            "distance_km", "duration_minutes", "base_fare", "per_km_rate",
            "per_minute_rate", "tolls", "estimated_fare", "currency", "fare_status",
            "expires_at", "created_by", "created_at",
        ]
        read_only_fields = ["estimated_fare", "created_by", "created_at"]

    def validate(self, attrs):
        user = self.context["request"].user
        bu = attrs.get("business_unit") or getattr(self.instance, "business_unit", None)
        if bu is not None and not user.can_access_business_unit(bu):
            raise serializers.ValidationError("Not authorized for this business unit.")
        ride_request = attrs.get("ride_request", getattr(self.instance, "ride_request", None))
        if ride_request is not None and bu is not None and ride_request.business_unit_id != bu.pk:
            raise serializers.ValidationError("Ride fare estimate ride request must belong to the same business unit.")
        trip = attrs.get("trip", getattr(self.instance, "trip", None))
        if trip is not None and bu is not None and trip.request.business_unit_id != bu.pk:
            raise serializers.ValidationError("Ride fare estimate trip must belong to the same business unit.")
        return attrs


class VehicleMaintenanceRecordSerializer(serializers.ModelSerializer):
    vehicle_plate = serializers.ReadOnlyField(source="vehicle.license_plate")
    completed_by_name = serializers.ReadOnlyField(source="completed_by.email", default=None)

    class Meta:
        model = VehicleMaintenanceRecord
        fields = [
            "id", "vehicle", "vehicle_plate", "business_unit",
            "maintenance_type", "description", "cost", "currency",
            "service_date", "completed_by", "completed_by_name", "notes",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        user = self.context["request"].user
        bu = attrs.get("business_unit") or getattr(self.instance, "business_unit", None)
        if bu is not None and not user.can_access_business_unit(bu):
            raise serializers.ValidationError("Not authorized for this business unit.")
        vehicle = attrs.get("vehicle", getattr(self.instance, "vehicle", None))
        if vehicle is not None and bu is not None and vehicle.business_unit_id != bu.pk:
            raise serializers.ValidationError("Vehicle must belong to the same business unit.")
        return attrs


class TransportationExpenseSerializer(serializers.ModelSerializer):
    vehicle_plate = serializers.ReadOnlyField(source="vehicle.license_plate", default=None)
    driver_name = serializers.ReadOnlyField(source="driver.user.email", default=None)
    submitted_by_name = serializers.ReadOnlyField(source="submitted_by.email", default=None)
    approved_by_name = serializers.ReadOnlyField(source="approved_by.email", default=None)

    class Meta:
        model = TransportationExpense
        fields = [
            "id", "reference", "business_unit", "expense_type", "vehicle",
            "vehicle_plate", "driver", "driver_name", "amount", "currency",
            "description", "status", "submitted_by", "submitted_by_name",
            "approved_by", "approved_by_name", "approved_at", "created_at",
        ]
        read_only_fields = ["submitted_by", "approved_by", "approved_at", "created_at"]

    def validate(self, attrs):
        user = self.context["request"].user
        bu = attrs.get("business_unit") or getattr(self.instance, "business_unit", None)
        if bu is not None and not user.can_access_business_unit(bu):
            raise serializers.ValidationError("Not authorized for this business unit.")
        vehicle = attrs.get("vehicle", getattr(self.instance, "vehicle", None))
        if vehicle is not None and bu is not None and vehicle.business_unit_id != bu.pk:
            raise serializers.ValidationError("Vehicle must belong to the same business unit.")
        driver = attrs.get("driver", getattr(self.instance, "driver", None))
        if driver is not None and bu is not None and driver.user.business_unit_id != bu.pk:
            raise serializers.ValidationError("Driver must belong to the same business unit.")
        return attrs
