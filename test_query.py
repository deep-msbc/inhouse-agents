import kuzu
db = kuzu.Database('/mnt/c/Users/yug.chauhan/Desktop/InHouseAgents/data/toolkit_graph.kuzu', read_only=True)
conn = kuzu.Connection(db)

# List all tables
r = conn.execute('SHOW TABLES')
tables = []
while r.has_next():
    tables.append(r.get_next()[0])

print('Tables found:', len(tables))
for t in tables:
    r = conn.execute(f'MATCH (n:{t}) RETURN count(n)')
    count = r.get_next()[0] if r.has_next() else 0
    print(f'  {t}: {count}')
