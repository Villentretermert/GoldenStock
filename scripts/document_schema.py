"""Export code metadata only, without connecting to a database or reading records."""
from pathlib import Path
from goldenstock.models import Base


def main():
    tables = sorted(Base.metadata.tables.values(), key=lambda table: table.name)
    lines = [
        '# GoldenStock: технический словарь данных\n',
        'Срез кода на 24 ноября 2026. Источник: `src/goldenstock/models.py`.\n',
        f'{len(tables)} прикладных таблиц. Служебная `alembic_version` учитывается отдельно.',
        'Это описание декларативной схемы, без чтения БД или пользовательских записей. '
        'Логические связи внутри JSON payload и серверные ACL не заменяются внешними ключами. '
        'Некоторые owner_id/org_id хранятся строками: наличие поля само по себе не обеспечивает изоляцию.',
    ]
    for table in tables:
        lines += [f'\n## {table.name}\n', '| Поле | Тип | PK | NULL | Внешний ключ |',
                  '|---|---|---|---|---|']
        for column in table.columns:
            links = ', '.join(sorted(fk.target_fullname for fk in column.foreign_keys)) or '—'
            lines.append(f'| {column.name} | {column.type} | {"да" if column.primary_key else ""} | '
                         f'{"да" if column.nullable else "нет"} | {links} |')
        unique = sorted(', '.join(c.name for c in constraint.columns)
                        for constraint in table.constraints
                        if constraint.__class__.__name__ == 'UniqueConstraint')
        if unique:
            lines += ['\nУникальность: ' + '; '.join(f'`{value}`' for value in unique) + '.']
    Path('docs/DATA_DICTIONARY_2026-11-24.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'Documented {len(tables)} tables from code metadata; no database access.')


if __name__ == '__main__':
    main()
