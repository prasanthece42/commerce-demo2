from pydantic import BaseModel, Field

import common as c

app = c.make_app("""
CREATE TABLE IF NOT EXISTS notifications_events(
  order_id text PRIMARY KEY, created_at timestamptz DEFAULT now()
);
""")


class Event(BaseModel):
    order_id: str = Field(pattern=r"^[a-zA-Z0-9-]{1,80}$")


@app.post("/events")
def notify(event: Event):
    with c.db.connection() as conn:
        conn.execute(
            "INSERT INTO notifications_events(order_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (event.order_id,),
        )
    return {
        "order_id": event.order_id,
        "status": "recorded",
        "external_message_sent": False,
    }
