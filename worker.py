import asyncio
from pyzeebe import ZeebeWorker, Job, create_camunda_cloud_channel

CLUSTER_ID = "f03961fc-6194-4dc6-a3a6-7870720e0ba0"
REGION = "bru-2"
CLIENT_ID = "GzjcEBwafwNPHDEpuyVEh3QqLn2BEIXK"
CLIENT_SECRET = "Yz~dNUNr0CIuuiuvCf87bMXLA5d4udA4lqvZ05UbtfOr0UeTZJ~S6VjOQgGhxz_v"


async def main():
    channel = create_camunda_cloud_channel(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        cluster_id=CLUSTER_ID,
        region=REGION,
    )

    worker = ZeebeWorker(channel)

    @worker.task(task_type="hello-world")
    async def handle_hello(job: Job):   # ← ключевое: аннотация job: Job
        print(f"Received task! Variables: {job.variables}")
        return {"greeting": "Hello from Python Worker!"}

    print("Worker started, waiting for tasks...")
    await worker.work()


if __name__ == "__main__":
    asyncio.run(main())
