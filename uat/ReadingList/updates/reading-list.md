# Reading List

Build a web application that keeps a list of books to read.

The reader can add a book with a title and author, view the books in the order added,
and remove a book. An empty title or author is rejected with a clear error message.

The application includes automated tests for each behavior.

The completed application provides a POSIX-compatible `bin/test.sh` that runs the complete
automated test suite from the application root. `sh bin/test.sh` exits zero only when every test
passes. The final build story runs this command after every implementation story and preserves its
command, exit code, standard output, and standard error as evidence.

The reader can mark a book as read and view whether each book is unread or read.
