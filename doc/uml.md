# ChargeSlot UML Class Diagram

The diagram shows the core SQLAlchemy domain entities and relationships implemented by the backend. It is intentionally focused on accounts, vehicles, charging infrastructure, and bookings.

```mermaid
classDiagram
    class User {
        +int id
        +string name
        +string email
        +UserRole role
        +bool is_active
        +ChargingMode default_charging_mode
        +int default_target_battery
        +int low_battery_threshold
    }

    class Vehicle {
        +int id
        +int user_id
        +string make
        +string model
        +float battery_kwh
        +ConnectorType connector_type
        +int current_soc
        +int target_soc
    }

    class Station {
        +int id
        +int operator_id
        +string name
        +string address
        +float latitude
        +float longitude
        +StationStatus status
    }

    class Charger {
        +int id
        +int station_id
        +float power_kw
        +CurrentType current_type
        +string gateway_id
        +bool is_active
    }

    class Connector {
        +int id
        +int charger_id
        +ConnectorType connector_type
        +ConnectorStatus status
    }

    class Booking {
        +int id
        +int user_id
        +int vehicle_id
        +int station_id
        +int charger_id
        +int slot_id
        +int start_soc
        +int target_soc
        +BookingStatus status
        +datetime start_time
        +datetime end_time
    }

    class UserRole {
        <<enumeration>>
        DRIVER
        OPERATOR
        ADMIN
    }

    class StationStatus {
        <<enumeration>>
        PENDING
        APPROVED
        REJECTED
        INACTIVE
    }

    class BookingStatus {
        <<enumeration>>
        HELD
        CONFIRMED
        ACTIVE
        COMPLETED
        CANCELLED
        NO_SHOW
        EXPIRED
        REASSIGNED
    }

    User "1" --> "0..*" Vehicle : owns
    User "1" --> "0..*" Booking : makes
    User "1" --> "0..*" Station : operates
    Vehicle "0..*" --> "0..1" Booking : associated with
    Station "1" *-- "0..*" Charger : contains
    Charger "1" *-- "0..*" Connector : provides
    User ..> UserRole : role
    Station ..> StationStatus : approval status
    Booking ..> BookingStatus : lifecycle
```

`Booking.station_id`, `charger_id`, and `slot_id` are stored as scalar fields in the current model; they are not declared as SQLAlchemy foreign-key relationships. The vehicle association is optional for a booking.
