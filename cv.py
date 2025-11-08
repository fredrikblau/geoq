import json

# Input & output files
INPUT_FILE = "db.json"
OUTPUT_FILE = "dbf.json"


def convert_entry(old):
    """Convert one entry from old format → new flattened format"""

    # Extract nested location safely
    location = old.get("location", {}) or {}
    latitude = location.get("latitude")
    longitude = location.get("longitude")

    # Extract nested contact safely
    contact = old.get("contact", {}) or {}
    phone = contact.get("phone", "")
    website = contact.get("website", "")
    instagram = contact.get("instagram", "")
    google_maps = contact.get("google_maps", "")

    new = {
        "category": old.get("category"),
        "name": old.get("name"),
        "description": old.get("description"),
        "address": old.get("address"),
        "latitude": latitude,
        "longitude": longitude,
        "best_time_to_visit": old.get("best_time_to_visit"),
        "approx_cost": old.get("approx_cost"),
        "duration_recommended": old.get("duration_recommended"),
        "local_tips": old.get("local_tips"),
        "phone": phone,
        "website": website,
        "instagram": instagram,
        "google_maps": google_maps,
        "source": old.get("source"),
        "raw_excerpt": old.get("raw_excerpt"),
        "confidence": old.get("confidence"),
    }

    return new


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        old_data = json.load(f)

    new_data = [convert_entry(entry) for entry in old_data]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)

    print(f"✅ Conversion completed!")
    print(f"💾 Output saved to {OUTPUT_FILE}")
    print(f"📦 Converted {len(new_data)} items")


if __name__ == "__main__":
    main()
