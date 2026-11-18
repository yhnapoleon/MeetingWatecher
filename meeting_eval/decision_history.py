"""Project per-meeting decision records onto the versions visible to a reader."""


def exact_reaffirmation(decision, candidates, source_id):
    matches = [row['id'] for row in candidates if row['source_id'] != source_id
               and row['attribute'] == decision['attribute'] and row['statement'] == decision['statement']]
    return matches[0] if len(matches) == 1 else None


def project_versions(rows, readable, history):
    versions = {}
    active = {}
    retired = set()
    visible = []
    for row in rows:
        did = row['id']
        same = row.get('reaffirms')
        replaces = row.get('supersedes')
        allowed = did in readable
        if allowed and not same and not replaces:
            # Old records and meetings with no shared history can still match literally.
            same = exact_reaffirmation(row, active.values(), row['source_id'])
            if same:
                row = dict(row, reaffirms=same)
        version = versions.get(same, same) if same else did
        versions[did] = version
        if not allowed:
            continue
        visible.append(row)
        if replaces:
            old_version = versions.get(replaces, replaces)
            retired.add(old_version)
            active.pop(old_version, None)
        if version not in retired:
            active[version] = row

    active_ids = {row['id'] for row in active.values()}
    selected = visible if history else [row for row in visible if row['id'] in active_ids]
    for row in selected:
        for relation in ('supersedes', 'reaffirms'):
            if row.get(relation) and row[relation] not in readable:
                row[relation] = None
    return selected
