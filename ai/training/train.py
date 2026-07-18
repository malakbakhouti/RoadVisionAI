from ultralytics import YOLO

# Charger le modèle YOLOv11
model = YOLO("yolo11n.pt")

# Entraîner sur notre dataset
model.train(
    data="../dataset/data.yaml",
    epochs=50,
    imgsz=640,
    batch=16,
    name="road_damage_model"
)

print("Entraînement terminé !")
