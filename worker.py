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
    async def handle_hello(job: Job):
        print(f"[hello-world] Received task! Variables: {job.variables}")
        return {"greeting": "Hello from Python Worker!"}

    @worker.task(task_type="send-notification")
    async def handle_notification(job: Job):
        approved = job.variables.get("approved", False)
        comment = job.variables.get("comment", "")
        print(f"[send-notification] START: approved={approved}, comment='{comment}'")
        await asyncio.sleep(2)  # имитация отправки email
        print(f"[send-notification] DONE")
        return {"notification_sent": True}

    @worker.task(task_type="archive-documents")
    async def handle_archive(job: Job):
        print(f"[archive-documents] START: process={job.process_instance_key}")
        await asyncio.sleep(3)  # имитация архивации
        print(f"[archive-documents] DONE")
        return {"archived": True}

    print("Worker started, waiting for tasks...")
    await worker.work()


if __name__ == "__main__":
    asyncio.run(main())
