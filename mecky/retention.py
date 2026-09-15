from datetime import datetime,timedelta,timezone
from .store import connect

def prune():
    db=connect()
    seven=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
    thirty=(datetime.now(timezone.utc)-timedelta(days=30)).isoformat()
    deleted={}
    for table,column,cutoff in (("conversation_messages","created_at",seven),("sessions","updated_at",seven),("feedback","created_at",thirty),("interactions","created_at",thirty)):
        deleted[table]=db.execute(f"DELETE FROM {table} WHERE {column}<?",(cutoff,)).rowcount
    db.commit();db.close()
    return deleted
