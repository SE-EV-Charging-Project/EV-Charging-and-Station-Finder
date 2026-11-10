# ChargeSlot Backend

FastAPI backend for **ChargeSlot — EV Charging Station Finder with Slot Dashboard and Auto-Booking System**.

## Feature Overview: Vehicle Battery Level Input (CS19-055 / REQ-F3-01)

Allows authenticated EV drivers to enter and dynamically update their current vehicle battery level (State of Charge / SoC) as a percentage (0% to 100%). Integrates with driving range calculations, energy estimates, and low-battery triggers.

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
