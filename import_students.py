import pandas as pd

from app.db.database import SessionLocal
from app.db.models import PatientORM

db = SessionLocal()

df = pd.read_excel("students_clean_import.xlsx")

for _, row in df.iterrows():

    student = PatientORM(
        id=str(row["id"]),
        name=row["name"],
        gender=row["gender"],
        class_name=row["class_name"],
        birth_date=str(row["birth_date"]),
        age=0
    )

    db.add(student)

db.commit()

print("Import siswa berhasil 😄🔥")