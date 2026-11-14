# ChargeSlot Backend

FastAPI backend for **ChargeSlot — EV Charging Station Finder with Slot Dashboard and Auto-Booking System**.

## Feature Overview: Battery Input and Charging Estimates (CS19-055 / CS19-056 / CS19-061)

Allows authenticated EV drivers to enter their vehicle's battery level as an integer percentage (0 to 100%) and estimate charging time and cost from the saved SoC, target SoC, battery capacity, effective charger power, and station tariff. Charging-time estimates include the 15-minute slot duration rounded up from the calculated charging time.

### Requirements & Traceability
- **Story ID:** CS19-055
- **SRS Requirement:** REQ-F3-01
- **Architecture Reference:** HLD §Booking / SDD §Estimator
- **Test Case IDs:** `TC-F3-01`, `STC-F3-01`
- **Related Acceptance Criteria:** Appendix B.1, Appendix B.2, REQ-F3-02, REQ-F3-20

---

## API Endpoints

### 1. Enter / Update Battery Level (SW Architecture Route)
- **Method:** `POST` or `PATCH`
- **Path:** `/api/v1/bookings/battery-level-input`
- **Auth:** Bearer Token (Driver or Admin)
- **Request Body:**
```json
{
  "battery_level": 45,
  "target_soc": 80,
  "vehicle_id": 1
}
```
> Note: If `vehicle_id` is omitted, the driver's active default vehicle is automatically selected.

- **Response:** `200 OK`
```json
{
  "vehicle_id": 1,
  "user_id": 10,
  "make": "Tata",
  "model": "Nexon EV",
  "registration_no": "KA01EV1111",
  "battery_kwh": 40.5,
  "current_soc": 45,
  "current_battery_percentage": 45,
  "target_soc": 80,
  "usable_range_km": 94.5,
  "estimated_range_km": 121.5,
  "energy_required_kwh": 15.75,
  "is_low_battery": false,
  "low_battery_threshold": 20,
  "battery_updated_at": "2026-11-10T09:40:00Z",
  "message": "Vehicle battery level updated successfully."
}
```

### 2. Inspect Current Battery Level & Range
- **Method:** `GET`
- **Path:** `/api/v1/bookings/battery-level-input?vehicle_id=1`
- **Auth:** Bearer Token (Driver or Admin)
- **Response:** `200 OK` (returns `BatteryLevelResponse`)

### 3. RESTful Vehicle Battery Resource
- **Set/Update:** `POST` / `PATCH` `/api/v1/vehicles/{vehicle_id}/battery`
- **Inspect:** `GET` `/api/v1/vehicles/{vehicle_id}/battery`
- **Default Vehicle Battery:** `GET` `/api/v1/vehicles/battery-level`

### 4. Battery Calculation Rules
- **Method:** `GET`
- **Path:** `/api/v1/bookings/battery-rules`
- **Auth:** Public / Authenticated
- **Response:** `200 OK` (returns Appendix B calculation formulas, reserves, and threshold constants)

---

## Calculation Rules (SRS Appendix B.1 & B.2)

1. **Usable Range (km):**
   $$\text{Usable Range} = \frac{\max(0, \text{SoC} - 10) / 100 \times \text{Battery Capacity (kWh)}}{\text{Consumption (kWh / 100 km)} / 100}$$
   *A 10 percentage point reserve is deducted to ensure the vehicle does not completely discharge.*

2. **Energy Required (kWh):**
   $$\text{Energy Required} = \frac{\max(0, \text{Target SoC} - \text{Current SoC}) / 100 \times \text{Battery Capacity (kWh)}}{0.90}$$
   *Assumes a standard 90% AC/DC charging efficiency.*

3. **Low Battery Assistance Flag:**
   $$\text{is\_low\_battery} = \text{Current SoC} \le \text{low\_battery\_threshold (default 20\%)}$$

---

### Charging Time Estimate (REQ-F3-07 / CS19-061)
- **Method:** `POST`
- **Path:** `/api/v1/bookings/charging-time-estimate`
- **Auth:** Bearer Token (Driver or Admin)
- **Request Body:**
```json
{
  "vehicle_id": 1,
  "charger_id": 2,
  "target_soc": 80
}
```
The vehicle must belong to the authenticated driver and have a saved battery level. The estimate uses energy required to reach the target SoC and the lower of the vehicle's AC/DC limit and the charger's rated power.

Battery-level and target percentages are integer values from 0 to 100; fractional values are rejected.

Estimated minutes = energy required (kWh) / effective charging power (kW) × 60.

The response includes `slot_length_minutes`, rounded up to the next 15-minute boundary (for example, 54 minutes requires a 60-minute slot; 0 minutes remains 0).

### Charging Cost Estimate (REQ-F3-09 / CS19-063)
- **Method:** `POST`
- **Path:** `/api/v1/bookings/cost-estimate`
- **Auth:** Bearer Token (Driver or Admin)
- **Request Body:**
```json
{
  "vehicle_id": 1,
  "station_id": 2,
  "target_soc": 80
}
```
The vehicle must belong to the authenticated driver and have a saved battery level. Cost is estimated as energy required in kWh multiplied by the station's configured `price_per_kwh`, rounded to two decimal places. The response currency is INR. A station without a configured tariff returns `409 Conflict`.

### Recommended Slots and Manual Booking (REQ-F3-10/11 / CS19-064/065)
- **Recommend:** `GET /api/v1/bookings/recommended-slots?vehicle_id=1&date=2026-11-13&target_soc=80`
- **Choose:** `POST /api/v1/bookings/manual-slot`
- **Auth:** Bearer Token (Driver or Admin)

Recommendations include approved active stations and operational compatible chargers, honor operating hours, maintenance windows, and existing active bookings, and rank slots by earliest start, then configured tariff (missing tariffs last), then slot duration. Results are limited to 50 by default; `limit` can be set from 1 to 200, and `station_id` can restrict the search. A connector marked occupied now may still be recommended for a future slot; reserved, faulted, and offline connectors are excluded.

The manual booking request must identify the station, charger, owned vehicle, start time, and target SoC. The service rechecks connector compatibility and availability before creating a confirmed booking; unique database claims for each 15-minute charger and vehicle interval prevent concurrent requests from booking the same charger slot or overlapping the same vehicle. Overlapping, blocked, or out-of-hours choices return `409 Conflict`.

```json
{
  "station_id": 2,
  "charger_id": 4,
  "vehicle_id": 1,
  "start_time": "2026-11-13T09:00:00Z",
  "target_soc": 80
}
```

### Temporary Slot Hold (REQ-F3-12 / CS19-066)
- **Method:** `POST`
- **Path:** `/api/v1/bookings/hold-slot`
- **Auth:** Bearer Token (Driver or Admin)

The request uses the same fields as manual booking. A successful response creates a `Held` booking and includes `hold_expires_at`, exactly five minutes after the hold is created. Expired holds no longer block a slot; payment processing is handled by the payment integration.

### Modify a Confirmed Booking (REQ-F3-23 / CS19-077)
- **Method:** `PATCH`
- **Path:** `/api/v1/bookings/{booking_id}`
- **Auth:** Bearer Token (booking owner or Admin)

The request contains a compatible `charger_id` and a new `start_time`. Only confirmed bookings can be changed, and the original booking must start at least 30 minutes in the future. The new slot must remain at the booking's station and pass the same availability, maintenance, charger, and vehicle-overlap checks as a new booking.

### Cancel a Booking (REQ-F3-24 / CS19-078)
- **Method:** `POST`
- **Path:** `/api/v1/bookings/{booking_id}/cancel`
- **Auth:** Bearer Token (booking owner or Admin)

Held and confirmed bookings can be cancelled before they start. Confirmed bookings cancelled at least 30 minutes before start incur no fee; later cancellations record a fee equal to 10% of estimated charging cost, rounded to INR paise. A station tariff and stored energy estimate are required to calculate a late fee. The response records the amount due; collection is left to the payment integration.

## Running Tests

Execute unit and integration tests using pytest:

```bash
cd chargeslot/backend
pytest tests/test_tc_f3_01_battery_level_input.py -vv
```

With code coverage:

```bash
pytest tests/test_tc_f3_01_battery_level_input.py --cov=app/booking --cov-report=term-missing
```
