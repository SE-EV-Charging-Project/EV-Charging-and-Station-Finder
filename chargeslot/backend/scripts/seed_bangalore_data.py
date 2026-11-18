"""
Seed script to populate SQLite database with realistic EV charging stations across Bangalore (Bengaluru).
Covers Central, Indiranagar, Koramangala, Whitefield, Electronic City, HSR Layout, Jayanagar,
Malleshwaram, Hebbal, Yelahanka, Yeshwanthpur, Rajajinagar, Marathahalli, and JP Nagar.
"""

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.db.session import SessionLocal
from app.models.user import User, UserRole
from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, CurrentType, ConnectorStatus
from app.models.vehicle import Vehicle, ConnectorType
from app.models.station_tariff import StationTariff
from app.utils.security import hash_password


BANGALORE_STATIONS = [
    {
        "name": "ChargeSlot Central - MG Road Metro Hub",
        "address": "1 MG-Lido Mall, Swami Vivekananda Rd, Trinity Circle, MG Road, Bengaluru, Karnataka 560001",
        "latitude": 12.9756,
        "longitude": 77.6066,
        "amenities": ["Wi-Fi", "Restrooms", "Cafeteria", "24/7 Security", "Shopping Mall", "Wheelchair Accessible"],
        "operating_hours": "24 hours",
        "contact_phone": "+91 80 2558 1001",
        "contact_email": "mgroad@chargeslot.in",
        "price_per_kwh": 18.50,
        "chargers": [
            {
                "name": "Delta Ultra-Fast DC 120kW",
                "power_kw": 120.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-MGR-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.CHADEMO, ConnectorStatus.AVAILABLE),
                ],
            },
            {
                "name": "Exicom Dual AC 22kW",
                "power_kw": 22.0,
                "current_type": CurrentType.AC,
                "gateway_id": "GW-MGR-AC01",
                "connectors": [
                    (ConnectorType.TYPE_2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.TYPE_2, ConnectorStatus.OCCUPIED),
                ],
            },
        ],
    },
    {
        "name": "ChargeSlot GreenHub - Indiranagar 100ft Rd",
        "address": "Plot 1045, 100 Feet Road, HAL 2nd Stage, Indiranagar, Bengaluru, Karnataka 560038",
        "latitude": 12.9716,
        "longitude": 77.6412,
        "amenities": ["Cafeteria", "High-speed Wi-Fi", "Restrooms", "Dining", "Covered Canopy"],
        "operating_hours": "06:00 - 23:00",
        "contact_phone": "+91 80 2521 2002",
        "contact_email": "indiranagar@chargeslot.in",
        "price_per_kwh": 19.00,
        "chargers": [
            {
                "name": "ABB Terra DC Fast 60kW",
                "power_kw": 60.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-IND-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                ],
            },
            {
                "name": "Schneider AC 22kW",
                "power_kw": 22.0,
                "current_type": CurrentType.AC,
                "gateway_id": "GW-IND-AC01",
                "connectors": [
                    (ConnectorType.TYPE_2, ConnectorStatus.AVAILABLE),
                ],
            },
        ],
    },
    {
        "name": "ChargeSlot Express - Koramangala 80ft Rd",
        "address": "Near Sony World Signal, 80 Feet Road, 6th Block, Koramangala, Bengaluru, Karnataka 560095",
        "latitude": 12.9352,
        "longitude": 77.6245,
        "amenities": ["Coffee Shop", "Restrooms", "ATM", "24/7 Security", "EV Lounge"],
        "operating_hours": "24 hours",
        "contact_phone": "+91 80 2553 3003",
        "contact_email": "koramangala@chargeslot.in",
        "price_per_kwh": 18.00,
        "chargers": [
            {
                "name": "Kempower Hypercharge 150kW",
                "power_kw": 150.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-KOR-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.CCS2, ConnectorStatus.OCCUPIED),
                ],
            },
            {
                "name": "Ather AC Commercial 22kW",
                "power_kw": 22.0,
                "current_type": CurrentType.AC,
                "gateway_id": "GW-KOR-AC01",
                "connectors": [
                    (ConnectorType.TYPE_2, ConnectorStatus.AVAILABLE),
                ],
            },
        ],
    },
    {
        "name": "ChargeSlot Hub - HSR 27th Main",
        "address": "Sector 1, 27th Main Road, Near Agara Lake, HSR Layout, Bengaluru, Karnataka 560102",
        "latitude": 12.9121,
        "longitude": 77.6446,
        "amenities": ["Restrooms", "Wi-Fi", "EV Lounge", "Snack Bar", "Lake View Walk"],
        "operating_hours": "24 hours",
        "contact_phone": "+91 80 2572 4004",
        "contact_email": "hsr@chargeslot.in",
        "price_per_kwh": 17.50,
        "chargers": [
            {
                "name": "Delta Fast DC 60kW",
                "power_kw": 60.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-HSR-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.CHADEMO, ConnectorStatus.AVAILABLE),
                ],
            },
            {
                "name": "Fortum AC Point 22kW",
                "power_kw": 22.0,
                "current_type": CurrentType.AC,
                "gateway_id": "GW-HSR-AC01",
                "connectors": [
                    (ConnectorType.TYPE_2, ConnectorStatus.AVAILABLE),
                ],
            },
        ],
    },
    {
        "name": "ChargeSlot TechHub - Whitefield ITPL",
        "address": "International Tech Park Bangalore (ITPL), Whitefield Main Rd, Bengaluru, Karnataka 560066",
        "latitude": 12.9855,
        "longitude": 77.7289,
        "amenities": ["Food Court", "Restrooms", "Wi-Fi", "Covered Parking", "Valet Charging", "Shopping Mall"],
        "operating_hours": "24 hours",
        "contact_phone": "+91 80 6695 5005",
        "contact_email": "whitefield@chargeslot.in",
        "price_per_kwh": 17.00,
        "chargers": [
            {
                "name": "Alpitronic Hypercharger 180kW",
                "power_kw": 180.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-WTF-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                ],
            },
            {
                "name": "Delta Dual DC 60kW",
                "power_kw": 60.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-WTF-DC02",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.GBT, ConnectorStatus.AVAILABLE),
                ],
            },
        ],
    },
    {
        "name": "ChargeSlot Silicon Point - Electronic City Phase 1",
        "address": "Opposite Infosys Gate 1, Hosur Road, Electronic City Phase 1, Bengaluru, Karnataka 560100",
        "latitude": 12.8452,
        "longitude": 77.6602,
        "amenities": ["Restrooms", "Cafeteria", "ATM", "24/7 Security", "Shaded Bays"],
        "operating_hours": "24 hours",
        "contact_phone": "+91 80 2852 6006",
        "contact_email": "ecity@chargeslot.in",
        "price_per_kwh": 16.50,
        "chargers": [
            {
                "name": "Tata Power EZ Charge 120kW",
                "power_kw": 120.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-ECT-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.CCS2, ConnectorStatus.OCCUPIED),
                ],
            },
            {
                "name": "Delta Dual AC 22kW",
                "power_kw": 22.0,
                "current_type": CurrentType.AC,
                "gateway_id": "GW-ECT-AC01",
                "connectors": [
                    (ConnectorType.TYPE_2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.TYPE_2, ConnectorStatus.AVAILABLE),
                ],
            },
        ],
    },
    {
        "name": "ChargeSlot South Point - Jayanagar 4th Block",
        "address": "11th Main Rd, Near BDA Complex, 4th Block, Jayanagar, Bengaluru, Karnataka 560011",
        "latitude": 12.9308,
        "longitude": 77.5838,
        "amenities": ["Shopping Complex", "Restrooms", "Vegetarian Food Court", "Covered Parking"],
        "operating_hours": "06:00 - 23:00",
        "contact_phone": "+91 80 2656 7007",
        "contact_email": "jayanagar@chargeslot.in",
        "price_per_kwh": 18.00,
        "chargers": [
            {
                "name": "ABB Terra DC 60kW",
                "power_kw": 60.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-JAY-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.CHADEMO, ConnectorStatus.AVAILABLE),
                ],
            },
            {
                "name": "Exicom AC 22kW",
                "power_kw": 22.0,
                "current_type": CurrentType.AC,
                "gateway_id": "GW-JAY-AC01",
                "connectors": [
                    (ConnectorType.TYPE_2, ConnectorStatus.AVAILABLE),
                ],
            },
        ],
    },
    {
        "name": "ChargeSlot EcoCharge - JP Nagar 6th Phase",
        "address": "Near Sarakki Lake, 15th Cross Road, JP Nagar 6th Phase, Bengaluru, Karnataka 560078",
        "latitude": 12.9063,
        "longitude": 77.5855,
        "amenities": ["Restrooms", "Park Walkway", "Wi-Fi", "Drinking Water"],
        "operating_hours": "07:00 - 22:00",
        "contact_phone": "+91 80 2659 8008",
        "contact_email": "jpnagar@chargeslot.in",
        "price_per_kwh": 17.50,
        "chargers": [
            {
                "name": "Servotech DC Fast 60kW",
                "power_kw": 60.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-JPN-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                ],
            },
            {
                "name": "Schneider AC 22kW",
                "power_kw": 22.0,
                "current_type": CurrentType.AC,
                "gateway_id": "GW-JPN-AC01",
                "connectors": [
                    (ConnectorType.TYPE_2, ConnectorStatus.AVAILABLE),
                ],
            },
        ],
    },
    {
        "name": "ChargeSlot Heritage - Malleshwaram Sampige",
        "address": "Sampige Road, 8th Cross, Malleshwaram, Bengaluru, Karnataka 560003",
        "latitude": 13.0031,
        "longitude": 77.5703,
        "amenities": ["Restrooms", "Heritage Cafe", "Covered Parking", "Drinking Water"],
        "operating_hours": "06:00 - 23:00",
        "contact_phone": "+91 80 2334 9009",
        "contact_email": "malleshwaram@chargeslot.in",
        "price_per_kwh": 18.50,
        "chargers": [
            {
                "name": "Delta Combo DC/AC 60kW",
                "power_kw": 60.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-MAL-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.TYPE_2, ConnectorStatus.AVAILABLE),
                ],
            },
        ],
    },
    {
        "name": "ChargeSlot Express - Rajajinagar Brigade Gateway",
        "address": "Dr. Rajkumar Road, Brigade Gateway Complex, Rajajinagar, Bengaluru, Karnataka 560055",
        "latitude": 12.9901,
        "longitude": 77.5526,
        "amenities": ["Restrooms", "Orion Mall", "Cinema", "Food Court", "Valet Parking"],
        "operating_hours": "24 hours",
        "contact_phone": "+91 80 2312 1010",
        "contact_email": "rajajinagar@chargeslot.in",
        "price_per_kwh": 19.50,
        "chargers": [
            {
                "name": "Delta Ultra-Fast DC 120kW",
                "power_kw": 120.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-RAJ-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                ],
            },
            {
                "name": "Ather AC 22kW",
                "power_kw": 22.0,
                "current_type": CurrentType.AC,
                "gateway_id": "GW-RAJ-AC01",
                "connectors": [
                    (ConnectorType.TYPE_2, ConnectorStatus.AVAILABLE),
                ],
            },
        ],
    },
    {
        "name": "ChargeSlot North Hub - Hebbal Manyata",
        "address": "Outer Ring Road, near Hebbal Flyover & Manyata Embassy Business Park, Bengaluru, Karnataka 560045",
        "latitude": 13.0358,
        "longitude": 77.5970,
        "amenities": ["Restrooms", "Drive-through Cafe", "24/7 Security", "Wi-Fi", "EV Care Center"],
        "operating_hours": "24 hours",
        "contact_phone": "+91 80 2362 1111",
        "contact_email": "hebbal@chargeslot.in",
        "price_per_kwh": 17.50,
        "chargers": [
            {
                "name": "Kempower Supercharge 150kW",
                "power_kw": 150.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-HEB-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.CCS2, ConnectorStatus.OCCUPIED),
                ],
            },
            {
                "name": "Delta Fast DC 60kW",
                "power_kw": 60.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-HEB-DC02",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.CHADEMO, ConnectorStatus.AVAILABLE),
                ],
            },
        ],
    },
    {
        "name": "ChargeSlot Airport Link - Yelahanka Hub",
        "address": "Bellary Road, Major Sandeep Unnikrishnan Rd, Yelahanka, Bengaluru, Karnataka 560064",
        "latitude": 13.1007,
        "longitude": 77.5963,
        "amenities": ["24/7 Highway Diner", "Clean Restrooms", "EV Lounge", "Airport Transit Desk"],
        "operating_hours": "24 hours",
        "contact_phone": "+91 80 2846 1212",
        "contact_email": "yelahanka@chargeslot.in",
        "price_per_kwh": 16.00,
        "chargers": [
            {
                "name": "ABB Terra DC 120kW",
                "power_kw": 120.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-YEL-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                ],
            },
            {
                "name": "Exicom AC 22kW",
                "power_kw": 22.0,
                "current_type": CurrentType.AC,
                "gateway_id": "GW-YEL-AC01",
                "connectors": [
                    (ConnectorType.TYPE_2, ConnectorStatus.AVAILABLE),
                ],
            },
        ],
    },
    {
        "name": "ChargeSlot RingRoad - Marathahalli Junction",
        "address": "Outer Ring Road, near Innovative Multiplex, Marathahalli, Bengaluru, Karnataka 560037",
        "latitude": 12.9569,
        "longitude": 77.7011,
        "amenities": ["Restrooms", "Food Court", "ATM", "24/7 Security"],
        "operating_hours": "24 hours",
        "contact_phone": "+91 80 2523 1313",
        "contact_email": "marathahalli@chargeslot.in",
        "price_per_kwh": 18.00,
        "chargers": [
            {
                "name": "Delta DC Fast 60kW",
                "power_kw": 60.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-MRT-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.TYPE_2, ConnectorStatus.AVAILABLE),
                ],
            },
        ],
    },
    {
        "name": "ChargeSlot EcoWay - Bannerghatta Road",
        "address": "Near Meenakshi Mall, Hulimavu, Bannerghatta Main Road, Bengaluru, Karnataka 560076",
        "latitude": 12.8787,
        "longitude": 77.5954,
        "amenities": ["Shopping Mall", "Restrooms", "Food Court", "Covered Parking", "Supermarket"],
        "operating_hours": "08:00 - 23:00",
        "contact_phone": "+91 80 2658 1414",
        "contact_email": "bannerghatta@chargeslot.in",
        "price_per_kwh": 17.00,
        "chargers": [
            {
                "name": "Servotech Dual DC 60kW",
                "power_kw": 60.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-BGH-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                ],
            },
            {
                "name": "Schneider AC 22kW",
                "power_kw": 22.0,
                "current_type": CurrentType.AC,
                "gateway_id": "GW-BGH-AC01",
                "connectors": [
                    (ConnectorType.TYPE_2, ConnectorStatus.AVAILABLE),
                ],
            },
        ],
    },
    {
        "name": "ChargeSlot Express - Yeshwanthpur Terminal",
        "address": "Tumkur Main Road, near Yeshwanthpur Metro & Railway Station, Bengaluru, Karnataka 560022",
        "latitude": 13.0232,
        "longitude": 77.5484,
        "amenities": ["Restrooms", "Transit Lounge", "24/7 Security", "Refreshment Kiosk", "Taxi Stand"],
        "operating_hours": "24 hours",
        "contact_phone": "+91 80 2337 1515",
        "contact_email": "yeshwanthpur@chargeslot.in",
        "price_per_kwh": 17.50,
        "chargers": [
            {
                "name": "Delta Fast DC 120kW",
                "power_kw": 120.0,
                "current_type": CurrentType.DC,
                "gateway_id": "GW-YSH-DC01",
                "connectors": [
                    (ConnectorType.CCS2, ConnectorStatus.AVAILABLE),
                    (ConnectorType.CHADEMO, ConnectorStatus.AVAILABLE),
                ],
            },
            {
                "name": "Ather AC 22kW",
                "power_kw": 22.0,
                "current_type": CurrentType.AC,
                "gateway_id": "GW-YSH-AC01",
                "connectors": [
                    (ConnectorType.TYPE_2, ConnectorStatus.AVAILABLE),
                ],
            },
        ],
    },
]


def seed_bangalore_data():
    db = SessionLocal()
    try:
        # 1. Ensure Operator User exists
        operator = db.query(User).filter(User.role == UserRole.OPERATOR).first()
        if not operator:
            operator = db.query(User).filter(User.email == "operator@chargeslot.in").first()
        if not operator:
            operator = User(
                name="ChargeSlot Bangalore Operations",
                email="operator@chargeslot.in",
                phone="+919876543210",
                hashed_password=hash_password("Operator@123"),
                role=UserRole.OPERATOR,
                is_verified=True,
                is_active=True,
                operator_organization="ChargeSlot Karnataka Network Pvt Ltd",
            )
            db.add(operator)
            db.commit()
            db.refresh(operator)
            print(f"[+] Created Operator user: ID={operator.id}, {operator.email}")
        else:
            print(f"[*] Found existing Operator: ID={operator.id}, {operator.email}")

        # 2. Ensure Driver User exists
        driver = db.query(User).filter(User.role == UserRole.DRIVER).first()
        if not driver:
            driver = User(
                name="Vaibhav EV Driver",
                email="driver@chargeslot.in",
                phone="+919876543211",
                hashed_password=hash_password("Driver@123"),
                role=UserRole.DRIVER,
                is_verified=True,
                is_active=True,
                default_target_battery=80,
                low_battery_threshold=20,
                default_search_radius=15,
            )
            db.add(driver)
            db.commit()
            db.refresh(driver)
            print(f"[+] Created Driver user: ID={driver.id}, {driver.email}")
        else:
            print(f"[*] Found existing Driver: ID={driver.id}, {driver.email}")

        # 3. Seed sample vehicles for Driver
        existing_vehicles = db.query(Vehicle).filter(Vehicle.user_id == driver.id).all()
        if not existing_vehicles:
            sample_vehicles = [
                Vehicle(
                    user_id=driver.id,
                    make="Tata",
                    model="Nexon EV Long Range",
                    battery_kwh=40.5,
                    connector_type=ConnectorType.CCS2,
                    max_ac_kw=7.2,
                    max_dc_kw=50.0,
                    consumption_kwh_100km=15.2,
                    registration_no="KA-01-EV-2024",
                    is_default=True,
                    current_soc=45,
                    target_soc=80,
                ),
                Vehicle(
                    user_id=driver.id,
                    make="MG",
                    model="ZS EV Excite",
                    battery_kwh=50.3,
                    connector_type=ConnectorType.CCS2,
                    max_ac_kw=7.4,
                    max_dc_kw=60.0,
                    consumption_kwh_100km=16.8,
                    registration_no="KA-03-EV-8899",
                    is_default=False,
                    current_soc=60,
                    target_soc=85,
                ),
                Vehicle(
                    user_id=driver.id,
                    make="Mahindra",
                    model="XUV400 EL",
                    battery_kwh=39.4,
                    connector_type=ConnectorType.CCS2,
                    max_ac_kw=7.2,
                    max_dc_kw=50.0,
                    consumption_kwh_100km=15.8,
                    registration_no="KA-05-EV-4422",
                    is_default=False,
                    current_soc=30,
                    target_soc=90,
                ),
            ]
            db.add_all(sample_vehicles)
            db.commit()
            print(f"[+] Seeded {len(sample_vehicles)} sample electric vehicles for driver ID={driver.id}")

        # 4. Seed Bangalore Charging Stations
        total_created = 0
        total_chargers = 0
        total_connectors = 0
        now_utc = datetime.now(timezone.utc)

        for s_data in BANGALORE_STATIONS:
            # Check if station with identical name already exists
            existing_st = db.query(Station).filter(Station.name == s_data["name"]).first()
            if existing_st:
                print(f"  [-] Station '{s_data['name']}' already exists (ID={existing_st.id}). Skipping.")
                continue

            station = Station(
                operator_id=operator.id,
                name=s_data["name"],
                address=s_data["address"],
                latitude=s_data["latitude"],
                longitude=s_data["longitude"],
                amenities=s_data["amenities"],
                operating_hours=s_data["operating_hours"],
                contact_phone=s_data["contact_phone"],
                contact_email=s_data["contact_email"],
                price_per_kwh=s_data["price_per_kwh"],
                status=StationStatus.APPROVED,
                is_active=True,
                reviewed_by_admin_id=None,
                reviewed_at=now_utc,
            )
            db.add(station)
            db.flush()  # Get station.id

            # Add StationTariff
            tariff = StationTariff(
                station_id=station.id,
                created_by_user_id=operator.id,
                price_per_kwh=s_data["price_per_kwh"],
                idle_fee_per_minute=1.0,
                tax_rate_percent=18.0,
                peak_periods=[
                    {"start_hour": 17, "end_hour": 21, "rate_multiplier": 1.25}
                ],
                effective_from=now_utc - timedelta(days=30),
            )
            db.add(tariff)

            # Add Chargers and Connectors
            for ch_data in s_data["chargers"]:
                charger = Charger(
                    station_id=station.id,
                    name=ch_data["name"],
                    power_kw=ch_data["power_kw"],
                    current_type=ch_data["current_type"],
                    gateway_id=ch_data["gateway_id"],
                    is_active=True,
                    is_out_of_service=False,
                )
                db.add(charger)
                db.flush()  # Get charger.id
                total_chargers += 1

                for conn_type, conn_status in ch_data["connectors"]:
                    connector = Connector(
                        charger_id=charger.id,
                        connector_type=conn_type,
                        status=conn_status,
                        last_update=now_utc,
                    )
                    db.add(connector)
                    total_connectors += 1

            total_created += 1

        db.commit()
        print(f"\n[✓] Successfully seeded {total_created} stations across Bangalore!")
        print(f"    Total Chargers created: {total_chargers}")
        print(f"    Total Connectors created: {total_connectors}")

    except Exception as exc:
        db.rollback()
        print(f"[!] Error seeding data: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_bangalore_data()

