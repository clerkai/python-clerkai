import hashlib
import os
from os.path import getsize, join


def ensure_clerkai_folder_versioning(clerkai_folder_path):
    from git import Repo

    if os.path.isdir(os.path.join(clerkai_folder_path, ".git")):
        # TODO make sure that this is a clerk-managed git repository
        repo = Repo(clerkai_folder_path)
    else:
        repo = Repo.init(clerkai_folder_path)
        # make the commits in this repo be from clerk automation by default
        config = repo.config_writer()
        config.set_value("user", "name", "Clerk.ai")
        config.set_value("user", "email", "automation@clerk.ai")
        config.release()
        # initial (empty) commit
        repo.index.commit(message="Initial commit")
    assert not repo.bare
    return repo


# add all untracked and changed files
def add_all_untracked_and_changed_files(repo):
    # track ignores within the git folder
    with open(
        os.path.join(repo.working_tree_dir, ".git", "info", "exclude"), "w"
    ) as text_file:
        text_file.write("Edits\n")
    repo.git.add("-A")
    uncommited_changes = repo.git.status("--porcelain")
    if uncommited_changes != "":
        repo.git.commit("-m", "Current files", "-a")


def short_gitsha1(repo, sha):
    short_sha = repo.git.rev_parse(sha, short=1)
    return short_sha


def current_gitsha1(repo):
    sha = repo.head.object.hexsha
    return short_gitsha1(repo, sha)


def current_gitcommit_datetime(repo):
    from datetime import datetime

    return datetime.fromtimestamp(repo.head.commit.authored_date)


def possibly_edited_commit_specific_df(
    df,
    export_file_name,
    edits_folder_path,
    commit_datetime,
    history_reference,
    create_if_not_exists,
):
    import pytz

    utc_commit_datetime = commit_datetime.astimezone(pytz.utc)

    commit_specific_directory = "%s (%s)" % (
        utc_commit_datetime.strftime("%Y-%m-%d %H%M"),
        history_reference,
    )
    commit_specific_directory_path = os.path.join(
        edits_folder_path, commit_specific_directory
    )
    # print("Checking if '%s/' exists" % (commit_specific_directory))
    if not os.path.isdir(commit_specific_directory_path):
        if create_if_not_exists:
            os.mkdir(commit_specific_directory_path)
        else:
            return False
    xlsx_path = os.path.join(commit_specific_directory_path, export_file_name)
    import pandas as pd

    # print("Checking if '%s/%s' exists" % (commit_specific_directory, export_file_name))
    if not os.path.isfile(xlsx_path):
        if create_if_not_exists:
            print("Creating '%s/%s'" % (commit_specific_directory, export_file_name))
            export_columns = df.columns
            with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
                df[export_columns].to_excel(
                    writer, sheet_name="Data", index=False, freeze_panes=(1, 0)
                )
        else:
            return False
    return pd.read_excel(os.path.join(commit_specific_directory_path, export_file_name))


def changes_between_two_commits(repo_base_path, from_commit, to_commit):
    from pydriller import RepositoryMining

    commits_iterator = RepositoryMining(
        repo_base_path, filepath=".", from_commit=from_commit, to_commit=to_commit
    ).traverse_commits()

    # follows file renames (ignores deletes and additions, so some new paths may have been
    # subsequently deleted, and some old paths may have not existed in the from_commit
    old_to_new_paths = {}
    new_to_old_paths = {}
    old_now_deleted_paths = {}  # TODO
    old_non_existing_now_added_paths = {}  # TODO
    for commit in commits_iterator:
        for modification in commit.modifications:
            if (
                modification.old_path
                and modification.new_path
                and modification.old_path != modification.new_path
            ):
                if modification.new_path in new_to_old_paths:
                    old_to_new_paths[
                        new_to_old_paths[modification.new_path]
                    ] = modification.new_path
                    new_to_old_paths[modification.new_path] = new_to_old_paths[
                        modification.new_path
                    ]
                else:
                    old_to_new_paths[modification.old_path] = modification.new_path
                    new_to_old_paths[modification.new_path] = modification.old_path
    del new_to_old_paths
    # print("old_to_new_paths", old_to_new_paths)

    return (old_to_new_paths, old_now_deleted_paths, old_non_existing_now_added_paths)


def merge_changes_from_previous_possibly_edited_df(
    df, edit_file, record_type, clerkai_folder_path, current_history_reference
):
    # set config based on record type
    if record_type == "transaction_files":
        additional_join_columns = []
        file_name_column_name = "File name"
        file_path_column_name = "File path"
    elif record_type == "transactions":
        additional_join_columns = [
            "naive_transaction_id",
            "naive_transaction_id_duplicate_num",
        ]
        file_name_column_name = "Source transaction file: File name"
        file_path_column_name = "Source transaction file: File path"
    else:
        raise ValueError("record_type '%s' not recognized" % record_type)

    previous_possibly_edited_df = edit_file["previous_possibly_edited_df"]

    # print("df.head(), edit_file, previous_possibly_edited_df.head()")
    # print(df.head(), edit_file, previous_possibly_edited_df.head())

    # get relevant from and to commits between the old and new edit files
    from_commit = edit_file["Related history reference"]
    to_commit = current_history_reference()

    (
        old_to_new_paths,
        old_now_deleted_paths,
        old_non_existing_now_added_paths,
    ) = changes_between_two_commits(clerkai_folder_path, from_commit, to_commit)

    def joined_path(record):
        return "%s/%s" % (record[file_name_column_name], record[file_path_column_name])

    df["clerkai_path"] = df.apply(joined_path, axis=1)

    previous_possibly_edited_df["clerkai_path"] = previous_possibly_edited_df.apply(
        joined_path, axis=1
    )

    def find_head_commit_corresponding_clerkai_path(clerkai_path):
        clerkai_path_key = clerkai_path.replace("@/", "")
        if clerkai_path_key in old_to_new_paths:
            return "@/%s" % old_to_new_paths[clerkai_path_key]
        else:
            # if no moves occurred just use the old path as is
            return clerkai_path

    previous_possibly_edited_df[
        "head_commit_corresponding_clerkai_path"
    ] = previous_possibly_edited_df["clerkai_path"].apply(
        find_head_commit_corresponding_clerkai_path
    )

    # create merge key
    # transaction files - head_commit_corresponding_clerkai_path
    # transactions - head_commit_corresponding_clerkai_path + ?

    import pandas as pd

    suffix = " (%s)" % from_commit

    def add_suffix(column_name):
        return "%s%s" % (column_name, suffix)

    merged_possibly_edited_df = pd.merge(
        df,
        previous_possibly_edited_df.add_suffix(suffix),
        how="outer",
        left_on=["clerkai_path", *additional_join_columns],
        right_on=[
            add_suffix(column_name)
            for column_name in [
                "head_commit_corresponding_clerkai_path",
                *additional_join_columns,
            ]
        ],
        suffixes=(False, False),
    )

    return merged_possibly_edited_df


def set_where_nan():
    pass


def propagate_previous_edits_from_across_columns(
    df_with_previous_edits_across_columns, previous_edit_files, editable_columns
):

    for history_reference in previous_edit_files["Related history reference"]:
        # print("history_reference", history_reference)
        suffix = " (%s)" % history_reference
        for column_name in editable_columns:
            suffixed_column_name = "%s%s" % (column_name, suffix)
            if column_name in df_with_previous_edits_across_columns.columns:
                df_where_column_is_null = df_with_previous_edits_across_columns[
                    df_with_previous_edits_across_columns[column_name].isnull()
                ]
                df_where_column_is_null[
                    column_name
                ] = df_with_previous_edits_across_columns[suffixed_column_name]
                df_with_previous_edits_across_columns[
                    column_name
                ] = df_where_column_is_null[column_name]
            else:
                df_with_previous_edits_across_columns[
                    column_name
                ] = df_with_previous_edits_across_columns[suffixed_column_name]
        # print("df_with_previous_edits_across_columns.head()", df_with_previous_edits_across_columns.head())

    return df_with_previous_edits_across_columns


def is_ignored_file(filename):
    if ".DS_Store" in filename:
        return True
    if ".~lock" in filename:
        return True


def sha256sum(filename):
    h = hashlib.sha256()
    b = bytearray(128 * 1024)
    mv = memoryview(b)
    with open(filename, "rb", buffering=0) as f:
        for n in iter(lambda: f.readinto(mv), 0):
            h.update(mv[:n])
    return h.hexdigest()


def sha1sum(filename):
    h = hashlib.sha1()
    b = bytearray(128 * 1024)
    mv = memoryview(b)
    with open(filename, "rb", buffering=0) as f:
        for n in iter(lambda: f.readinto(mv), 0):
            h.update(mv[:n])
    return h.hexdigest()


def list_files_in_folder(folder_path):
    def is_not_ignored_file(filename):
        return not is_ignored_file(filename)

    all_files = []
    for root, dirs, files in os.walk(folder_path):
        # print(root, "consumes", end=" ")
        # print(sum(getsize(join(root, name)) for name in files), end=" ")
        # print("bytes in", len(files), "non-directory files")
        if ".git" in dirs:
            dirs.remove(".git")  # don't visit .git directories
        files = filter(is_not_ignored_file, files)
        # print(image_files)
        for file in list(files):
            file_sha256sum = sha256sum(join(root, file))
            file_sha1sum = sha1sum(join(root, file))
            all_files.append(
                {
                    "File name": file,
                    "File path": root,
                    "File metadata": {
                        "size": getsize(join(root, file)),
                        "sha1sum": file_sha1sum,
                        "sha256sum": file_sha256sum,
                    },
                }
            )
    return all_files


def list_files_in_clerk_subfolder(folder_path, clerkai_folder_path, repo):
    import pandas as pd

    _ = pd.DataFrame(list_files_in_folder(folder_path))
    if len(_) > 0:
        _["File path"] = _["File path"].apply(
            lambda root: root.replace(clerkai_folder_path, "@/")
        )
    return _
