import json
import cv2
import numpy as np

from keras_facenet import FaceNet
from sklearn.metrics.pairwise import cosine_similarity

embedder = FaceNet()


class FaceService:

    def __init__(self):
        self.embedder = embedder

    def read_image(self, image_bytes):
        np_array = np.frombuffer(image_bytes, np.uint8)

        image = cv2.imdecode(np_array, cv2.IMREAD_COLOR)

        if image is None:
            raise ValueError("Gambar tidak valid")

        return image

    def generate_embedding(self, image_bytes):

        image = self.read_image(image_bytes)

        faces = self.embedder.extract(image, threshold=0.95)

        if len(faces) == 0:
            raise ValueError("Wajah tidak ditemukan")

        if len(faces) > 1:
            raise ValueError("Harap hanya ada satu wajah")

        return faces[0]["embedding"]

    def embedding_to_json(self, embedding):
        return json.dumps(embedding.tolist())

    def json_to_embedding(self, json_data):
        return np.array(json.loads(json_data))

    def calculate_similarity(self, emb1, emb2):

        similarity = cosine_similarity(
            [emb1],
            [emb2]
        )[0][0]

        return float(similarity)

    def verify(self, new_embedding, saved_embedding, threshold=0.75):

        score = self.calculate_similarity(
            new_embedding,
            saved_embedding
        )

        return {
            "match": score >= threshold,
            "score": score
        }


face_service = FaceService()