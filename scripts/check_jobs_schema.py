import sqlalchemy
e = sqlalchemy.create_engine("sqlite:///devagents.db")
cols = [c["name"] for c in sqlalchemy.inspect(e).get_columns("jobs")]
print("jobs columns:", cols)
