# Data

Общие структуры и обработка табличного запроса. `query_schema.py` задает
Pydantic-схемы, `query_parser.py` преобразует SQL-подобный текст, `query_values.py`
нормализует значения, `sources.py` хранит alias источников, а `result_wrapper.py`
добавляет прозрачное описание результата вокруг data-tools.
