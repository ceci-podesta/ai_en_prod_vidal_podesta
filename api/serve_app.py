import time

import ray
from ray import serve

from main import app


@serve.deployment(
    num_replicas=2,
    max_queued_requests=100,
)
@serve.ingress(app)
class OilGasAPI:
    pass


if __name__ == "__main__":
    ray.init()
    serve.start(http_options={"host": "0.0.0.0", "port": 8000})
    serve.run(OilGasAPI.bind())
    print("Ray Serve corriendo en http://0.0.0.0:8000 con 2 replicas")
    while True:
        time.sleep(3600)
