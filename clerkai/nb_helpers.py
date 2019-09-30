import os

from clerkai.transactions.flow import transactions_flow
from clerkai.utils import (add_all_untracked_and_changed_files,
                           current_gitsha1, ensure_clerkai_folder_versioning,
                           list_files_in_clerk_subfolder,
                           possibly_edited_df_util, short_gitsha1)


def extract_commit_sha_from_edit_subfolder_path(edit_subfolder_path):
    import re

    p = re.compile("\\(([^)]*)\\)", re.IGNORECASE)
    m = p.search(edit_subfolder_path)
    commit_sha = None
    if len(m.groups()) > 0:
        commit_sha = m.groups()[0]
    return commit_sha


def init_notebook_and_return_helpers(clerkai_folder, downloads_folder, pictures_folder):
    # expand given paths to absolute paths
    clerkai_folder_path = os.path.expanduser(clerkai_folder)
    transactions_folder_path = os.path.join(clerkai_folder_path, "Transactions")
    receipts_folder_path = os.path.join(clerkai_folder_path, "Receipts")
    edits_folder_path = os.path.join(clerkai_folder_path, "Edits")
    travels_folder_path = os.path.join(clerkai_folder_path, "Travels")
    downloads_folder_path = os.path.expanduser(downloads_folder)
    pictures_folder_path = os.path.expanduser(pictures_folder)

    # set working dir to be the clerk.ai folder
    os.chdir(clerkai_folder_path)

    # initiate / validate clerk.ai-folder versioning
    repo = ensure_clerkai_folder_versioning(clerkai_folder_path)

    def acknowledge_changes_in_clerkai_folder():
        add_all_untracked_and_changed_files(repo)

    def current_history_reference():
        return current_gitsha1(repo)

    # transactions

    transaction_files_editable_columns = [
        "Ignore",
        "Account provider",
        "Account",
        "Content type",
        "Account currency",
    ]

    transactions_editable_columns = [
        "Include in expense report",
        "Expense report receiver",
        "Expense report",
        "Expense report accounting period",
        "Walletsharing",
        "Real Date (Corrected)",
        "Days between real and bank dates",
        "Doc Source",
        "Doc Status",
        "Doc",
        "Clarification",
    ]

    # Account	Date initiated	Date settled	Source text	Merchant	Hash	Transaction id	Amount (Incl. VAT)	Balance	Original amount (In local currency)	Local currency	Account Owner	Comments / Notes	Doc notes	Doc filename	Doc link	Doc inbox search	Sorting ordinal	Legacy Id	Date initiated value	Date settled value	Absolute amount	Absolute original amount	Vendor	Category	Description	Status	Invoice date	Paid date	Source	Amount	Currency	Status

    def list_transactions_files_in_transactions_folder():
        _ = list_files_in_clerk_subfolder(
            transactions_folder_path, clerkai_folder_path, repo
        )
        for column in transaction_files_editable_columns:
            _[column] = None
        _["History reference"] = current_history_reference()
        return _[
            [
                "File name",
                "File path",
                *transaction_files_editable_columns,
                "File metadata",
                "History reference",
            ]
        ]

    def transactions(keep_unmerged_previous_edits=False, failfast=False):
        return transactions_flow(
            transaction_files_editable_columns=transaction_files_editable_columns,
            transactions_editable_columns=transactions_editable_columns,
            list_transactions_files_in_transactions_folder=list_transactions_files_in_transactions_folder,
            possibly_edited_df=possibly_edited_df,
            transactions_folder_path=transactions_folder_path,
            acknowledge_changes_in_clerkai_folder=acknowledge_changes_in_clerkai_folder,
            clerkai_file_path=clerkai_file_path,
            current_history_reference=current_history_reference,
            keep_unmerged_previous_edits=keep_unmerged_previous_edits,
            failfast=failfast,
        )

    # receipts

    def list_receipt_files_in_receipts_folder():
        _ = list_files_in_clerk_subfolder(
            receipts_folder_path, clerkai_folder_path, repo
        )
        _["Ignore"] = None
        _["History reference"] = current_history_reference()
        return _[
            ["File name", "File path", "Ignore", "File metadata", "History reference"]
        ]

    # other

    def list_edit_files_in_edits_folder():
        _ = list_files_in_clerk_subfolder(edits_folder_path, clerkai_folder_path, repo)
        if len(_) > 0:
            from pydriller import RepositoryMining

            commits_iterator = RepositoryMining(
                clerkai_folder_path, filepath="."
            ).traverse_commits()
            commits = {}
            for commit in commits_iterator:
                history_reference = short_gitsha1(repo, commit.hash)
                commits[history_reference] = commit
            _["Related history reference"] = _["File path"].apply(
                extract_commit_sha_from_edit_subfolder_path
            )

            def commit_datetime_from_history_reference(history_reference):
                return commits[history_reference].author_date

            _["Related history reference date"] = _["Related history reference"].apply(
                commit_datetime_from_history_reference
            )
            _ = _.sort_values(by="Related history reference date")
        return _

    # TODO: make this guess which ones are transactions
    def list_transactions_files_in_downloads_folder():
        transaction_files = []
        for file_name in os.listdir(downloads_folder_path):
            if "Transaktioner" in file_name:
                transaction_files.append(file_name)
        return transaction_files

    def clerkai_file_path(file):
        return os.path.join(
            file["File path"].replace("@", clerkai_folder_path), file["File name"]
        )

    # ensure_directories_are_in_place()
    if not os.path.isdir(transactions_folder_path):
        os.mkdir(transactions_folder_path)
    if not os.path.isdir(receipts_folder_path):
        os.mkdir(receipts_folder_path)
    if not os.path.isdir(edits_folder_path):
        os.mkdir(edits_folder_path)
    if not os.path.isdir(downloads_folder_path):
        raise Exception("Downloads folder missing")
    if not os.path.isdir(pictures_folder_path):
        raise Exception("Pictures folder missing")

    def possibly_edited_df(
        current_commit_df,
        record_type,
        editable_columns,
        keep_unmerged_previous_edits=False,
    ):
        return possibly_edited_df_util(
            current_commit_df,
            record_type,
            editable_columns,
            keep_unmerged_previous_edits,
            list_edit_files_in_edits_folder,
            current_history_reference,
            edits_folder_path,
            clerkai_folder_path,
            repo,
        )

    return (
        acknowledge_changes_in_clerkai_folder,
        current_history_reference,
        transactions,
        list_receipt_files_in_receipts_folder,
        list_edit_files_in_edits_folder,
        list_transactions_files_in_downloads_folder,
        clerkai_file_path,
        possibly_edited_df,
    )
