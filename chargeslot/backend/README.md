# ChargeSlot Backend

FastAPI backend for **ChargeSlot — EV Charging Station Finder with Slot Dashboard and Auto-Booking System**.

## Feature Overview: Battery Input and Charging Estimates (CS19-055 / CS19-056 / CS19-061)

Allows authenticated EV drivers to enter their vehicle's battery level as an integer percentage (0 to 100%) and estimate required energy, charging time, and cost from the saved SoC, target SoC, battery capacity, effective charger power, and station tariff. Charging-time estimates include the 15-minute slot duration rounded up from the calculated charging time.

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

### Energy Estimate (REQ-F3-06 / CS19-060)
- **Method:** `POST`
- **Path:** `/api/v1/bookings/energy-estimate`
- **Auth:** Bearer Token (Driver or Admin)
- **Request Body:**
```json
{
  "vehicle_id": 1,
  "target_soc": 80
}
```
The vehicle must belong to the authenticated driver and have a saved battery level. The estimate uses the vehicle battery capacity and existing 90% charging-efficiency rule. The response includes current and target SoC, capacity, and required energy in kWh. If the vehicle is already at or above the target, required energy is zero.

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

The manual booking request must identify the station, charger, owned vehicle, start time, and target SoC. The service rechecks connector compatibility and availability before creating a five-minute `Held` booking; it becomes `Confirmed` only after the reservation-fee order is verified. Unique database claims for each 15-minute charger and vehicle interval prevent concurrent requests from booking the same charger slot or overlapping the same vehicle. Overlapping, blocked, or out-of-hours choices return `409 Conflict`.

### Vehicle-Compatible Station Filtering (REQ-F3-05 / CS19-059)
- **Method:** `GET`
- **Path:** `/api/v1/stations/filter-stations?vehicle_id=1`
- **Auth:** Bearer Token (Driver or Admin)

When `vehicle_id` is supplied, results require an operational charger with the same connector type and a positive vehicle power limit for that charger's current type (AC or DC). Each result includes `vehicle_compatible_max_power_kw`, the greatest effective rate across compatible chargers, capped at the vehicle's corresponding maximum. A charger rated above the vehicle limit remains compatible and reports the capped rate. Drivers may only filter with their own vehicles.

```json
{
  "station_id": 2,
  "charger_id": 4,
  "vehicle_id": 1,
  "start_time": "2026-11-13T09:00:00Z",
  "target_soc": 80
}
```

### Reachability Filtering (REQ-F3-04 / CS19-058)
- **Method:** `GET`
- **Path:** `/api/v1/stations/reachable?vehicle_id=1&latitude=12.97&longitude=77.59`
- **Auth:** Bearer Token (Driver or Admin)

The endpoint requires a saved vehicle battery level and returns only operational, connector-compatible stations whose road distance is no greater than the vehicle's usable range (which reserves 10% battery). The response includes both great-circle `distance_km` and routed `road_distance_km`. Configure `ROUTING_SERVICE_URL` to point to a self-hosted OSRM-compatible routing service; the default is `http://localhost:5000`. If routing is unavailable or returns invalid data, the API reports an error rather than substituting straight-line distance.

### Temporary Slot Hold (REQ-F3-12 / CS19-066)
- **Method:** `POST`
- **Path:** `/api/v1/bookings/hold-slot`
- **Auth:** Bearer Token (Driver or Admin)

The request uses the same fields as manual booking. A successful response creates a `Held` booking and includes the reservation fee and `hold_expires_at`, exactly five minutes after the hold is created. Expired holds no longer block a slot.

### Confirm a Booking (REQ-F3-15 / CS19-069)
- **Method:** `POST`
- **Path:** `/api/v1/bookings/{booking_id}/payment-confirmation`
- **Auth:** `X-Payment-Webhook-Secret` shared secret, configured with `PAYMENT_WEBHOOK_SECRET`

The provider adapter posts an INR payment event with a unique `provider_event_id`, the amount, and `Succeeded` or `Failed` status. A successful event confirms the booking only when the amount matches its reservation fee and the hold has not expired. Provider-event replays are idempotent. A late or mismatched successful payment is recorded as due for refund; this ledger does not charge or refund real money. Confirmation returns a booking reference and a signed check-in QR payload.

### Modify a Confirmed Booking (REQ-F3-23 / CS19-077)
- **Method:** `PATCH`
- **Path:** `/api/v1/bookings/{booking_id}`
- **Auth:** Bearer Token (booking owner or Admin)

The request contains a compatible `charger_id` and a new `start_time`. Only confirmed bookings can be changed, and the original booking must start at least 30 minutes in the future. The new slot must remain at the booking's station and pass the same availability, maintenance, charger, and vehicle-overlap checks as a new booking.

### Cancel a Booking (REQ-F3-24 / CS19-078)
- **Method:** `POST`
- **Path:** `/api/v1/bookings/{booking_id}/cancel`
- **Auth:** Bearer Token (booking owner or Admin)

Held and confirmed bookings can be cancelled before they start. Confirmed bookings cancelled at least 30 minutes before start incur no fee; later cancellations record a fee equal to 10% of estimated charging cost, rounded to INR paise. Captured reservation fees and session payments are automatically refunded less any cancellation fee. Refunds are submitted to the gateway with an idempotency key and tracked against a five-weekday deadline; a gateway failure is returned explicitly and can be retried through the refund endpoint.

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

### Live Charging Session Monitor (REQ-F3-29 / CS19-083)

The gateway can submit normalized OCPP meter samples to `POST /api/v1/gateway/ocpp/1.6j/meter-values` using `X-Gateway-Secret` or an Operator/Admin bearer token. Supply a `connector_id` or `gateway_id` with a 1-based `connector_index`, along with `power_kw`, cumulative imported `energy_meter_kwh`, and an optional `observed_at`, `transaction_id`, and idempotency key. Power must be non-negative and no more than 110% of the charger's rated power; cumulative energy cannot decrease during a session. A sample is accepted only when exactly one booking on that charger is active.

Drivers can read their own active session at `GET /api/v1/bookings/{booking_id}/live-monitor`; the station's Operator and an Admin may also read it. The response includes the latest measured power, energy delivered since the first stored meter sample, estimated SoC, elapsed time since that first sample, and estimated cost in INR. SoC uses the booking's start SoC, vehicle battery capacity, and the existing 90% charging-efficiency assumption. Cost is `energy_kwh × station price_per_kwh`; it is `null` when no tariff is configured. Missing telemetry is reported as `has_telemetry: false` with measurement fields unset rather than fabricated values.

Clients should poll the monitor endpoint every 30 seconds. A reading is reported stale when its observation is more than 30 seconds old. The gateway endpoint expects normalized power in kW and cumulative imported energy in kWh; an OCPP adapter must convert its `MeterValues` samples to these units before submission.

### Stop an Active Charging Session (REQ-F3-30)

The booking owner or an Admin can request a stop with `POST /api/v1/bookings/{booking_id}/stop-session`. The booking must be active and have a recent meter reading associated with an OCPP transaction ID. The API queues a durable `RemoteStopTransaction`; repeating the request while that transaction is pending or accepted returns the existing command. This endpoint queues the request only and does not claim the charger has stopped.

Authenticated gateways poll `GET /api/v1/gateway/ocpp/1.6j/commands?gateway_id=GW-ID` with `X-Gateway-Secret` or an Operator/Admin bearer token. Pending commands remain available until a result is reported to `POST /api/v1/gateway/ocpp/1.6j/commands/{command_id}/result` as `Accepted` or `Rejected`. When measured energy since the first session meter sample reaches `booking.est_energy_kwh`, meter ingestion queues the same stop command automatically. If no transaction ID is available, the meter response reports that the target was reached but no command could be queued.

Only a gateway `StopTransaction` confirmation sent to `POST /api/v1/gateway/ocpp/1.6j/stop-transaction` marks the booking `Completed`. Submit `gateway_id`, `transaction_id`, `meter_stop_wh`, and `observed_at`; an optional `idempotency_key` (or OCPP `messageId`) makes retries safe. The gateway is responsible for translating the queued command into OCPP and reporting the protocol result and final transaction event.

## Payments, Billing, Tariffs, and Analytics (CS19-088–113)

Payment methods are UPI, debit/credit card, and net banking through Razorpay. Configure `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`; set `RAZORPAY_WEBHOOK_SECRET` for signed webhook processing. The reservation fee defaults to INR 50 and can be changed with `RESERVATION_FEE_INR`. New tariffs default to no idle fee and zero tax until the operator configures them. Amounts sent to Razorpay and stored in the ledger are integer paise.

### Booking and session payment flow

1. `POST /api/v1/bookings/manual-slot` or `/api/v1/bookings/hold-slot` creates a five-minute `Held` booking.
2. Create the reservation order with `POST /api/v1/payments/bookings/{booking_id}/reservation/order`:
   ```json
   {"payment_method": "upi", "idempotency_key": "reservation-<unique-client-key>"}
   ```
3. Verify the gateway result at `POST /api/v1/payments/verify`. The server validates the Razorpay signature and fetches both order and payment from Razorpay before confirming the booking and snapshotting the effective tariff.
4. On OCPP `StopTransaction`, the system computes the final bill from metered energy, idle time after the slot, the tariff snapshot, and tax, less the captured reservation fee. Any unpaid balance sets `payment_due` and blocks new bookings.
5. Create a balance order with `POST /api/v1/payments/bookings/{booking_id}/balance/order`, then verify it in the same way. A signed `payment.failed` webhook preserves `Payment Due`.

All order and refund requests carry an idempotency key. Clients should supply the same key when retrying a request; the returned order is reused instead of creating another charge. The payment ledger records order/payment references, type, status, amount, and timestamps.

### Refunds, invoices, and history

Cancellation automatically requests refunds for captured booking payments, deducting the recorded cancellation fee. `POST /api/v1/payments/bookings/{booking_id}/refund` is available for a retry with a new idempotency key. Refund status and due date are returned, and signed gateway refund webhooks update the ledger.

Drivers can view their date-sorted payment ledger at `GET /api/v1/payments/history`. A completed session's paid invoice is available as a PDF at `GET /api/v1/billing/bookings/{booking_id}/invoice`; only the booking owner or an administrator can access it.

### Operator tariffs

Operators can read and version their own station tariff at `GET` and `PUT /api/v1/stations/{station_id}/tariff`; administrators can manage any station. A tariff contains INR/kWh, idle INR/minute, tax percentage, and peak periods. Peak period times are UTC `HH:MM` values with a positive multiplier. Tariff changes are effective immediately; clients cannot supply an effective date. Each confirmed booking retains the price, idle fee, tax, and peak-period snapshot that was in force at confirmation.

### Reconciliation

Administrators can run or rerun a daily payment/refund comparison with `POST /api/v1/payments/reconciliation/daily?reconciled_on=YYYY-MM-DD`; the default is the previous UTC day. The run and any missing or mismatched gateway references are persisted. For unattended daily execution, schedule `python -m app.daily_reconciliation` from `chargeslot/backend` once per day. This command uses the configured database and an existing administrator account.

### Usage, earnings, and platform analytics

Authenticated users can read their role-scoped analytics at `GET /api/v1/analytics/summary?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&granularity=week`; `granularity` also accepts `month`, and the default date range is the previous 30 UTC days. Drivers receive their session count, energy, net captured spend, estimated CO₂ savings, weekly/monthly trends, and most-used stations. Operators receive the same station-level sessions, energy, net revenue, and utilization metrics only for stations they own. Administrators receive platform session, energy, revenue, user, and station totals. The CSV export at `GET /api/v1/analytics/export.csv` uses the same date and role scope.

CO₂ savings are estimates using `CO2_SAVED_KG_PER_KWH` (default 0.7 kg per delivered kWh); deployments should configure a factor appropriate to their chosen comparison methodology. Analytics are stored in a shared snapshot that refreshes on first use and whenever it is at least one hour old. To refresh even when no analytics requests are made, schedule `python -m app.refresh_analytics` from `chargeslot/backend` at least hourly.
