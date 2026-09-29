"""
Run once after the tables are created (they're created automatically the
first time the API starts) to load 5 sample teachers with open slots.

    python -m app.seed
"""
from datetime import datetime, timedelta, timezone
from .database import SessionLocal, Base, engine
from .models import Teacher, TeacherSlot

Base.metadata.create_all(bind=engine)


def run():
    db = SessionLocal()
    if db.query(Teacher).count() > 0:
        print("Teachers already exist - skipping seed (delete rows first if you want to reseed).")
        return

    now = datetime.now(timezone.utc)

    teachers_data = [
        dict(
            name="Radha Krishnan", art_form="Bharatanatyam",
            bio="Trained at Kalakshetra, 15 years teaching children abroad online.",
            verified=True, institution="Kalakshetra Foundation",
            slot_offsets=[(2, 10), (4, 17), (7, 10)],
        ),
        dict(
            name="Lakshmi Menon", art_form="Mohiniyattam",
            bio="Kerala Kalamandalam graduate, specializes in beginner-friendly classes.",
            verified=True, institution="Kerala Kalamandalam",
            slot_offsets=[(1, 9), (3, 18), (6, 9)],
        ),
        dict(
            name="Hari Narayanan", art_form="Kathakali",
            bio="Third-generation Kathakali artist, teaches storytelling through movement.",
            verified=True, institution="Kerala Kalamandalam",
            slot_offsets=[(2, 19), (5, 19)],
        ),
        dict(
            name="Saraswathy Iyer", art_form="Carnatic Music",
            bio="Vocal training for kids aged 6+, patient and encouraging style.",
            verified=True, institution="RLV College of Music & Fine Arts",
            slot_offsets=[(1, 16), (3, 16), (8, 16)],
        ),
        dict(
            name="Arjun Pillai", art_form="Percussion",
            bio="Chenda and Mridangam specialist, makes rhythm fun for young beginners.",
            verified=True, institution="RLV College of Music & Fine Arts",
            slot_offsets=[(2, 11), (4, 11)],
        ),
    ]

    for t_data in teachers_data:
        offsets = t_data.pop("slot_offsets")
        teacher = Teacher(**t_data)
        db.add(teacher)
        db.flush()  # get teacher.id before commit
        for days, hour in offsets:
            slot_time = (now + timedelta(days=days)).replace(
                hour=hour, minute=0, second=0, microsecond=0
            )
            db.add(TeacherSlot(teacher_id=teacher.id, slot_time=slot_time))

    db.commit()
    print(f"Seeded {len(teachers_data)} teachers with their slots.")


if __name__ == "__main__":
    run()
