"""Copy local invoices and extraction JSON into the private Supabase bucket."""

from app.storage import sync_local_to_supabase


if __name__ == "__main__":
    counts = sync_local_to_supabase()
    print(
        f"done uploads={counts['uploads']} extractions={counts['extractions']} total={counts['total']}"
    )
