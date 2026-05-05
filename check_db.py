#!/usr/bin/env python
import kuzu

db = kuzu.Database('/mnt/c/Users/yug.chauhan/Desktop/InHouseAgents/data/toolkit_graph.kuzu', read_only=True)
conn = kuzu.Connection(db)

# Show all tables
r = conn.execute("CALL show_tables() RETURN *")
df = r.get_as_df()
print("Tables in DB:")
print(df)
print()

# Count nodes
tables = ['SourceFile', 'ExportedSymbol', 'Package', 'Component', 'Feature', 'TypeDef']
for table in tables:
    try:
        r = conn.execute(f'MATCH (n:{table}) RETURN count(n)')
        count = r.get_next()[0] if r.has_next() else 0
        print(f'{table}: {count}')
    except Exception as e:
        print(f'{table}: ERROR - {str(e)[:80]}')
