Ngspice pipe mode
=================

sim2 currently uses Ngspice in pipe mode (:code:`ngspice -p`). Unfortunately, Ngspice has slightly different I/O behavior depending on whether it is built with libreadline, libedit or neither.

Behavior with neither libreadline nor libedit::

    $ echo -e "echo hello\necho world\nquit" | /home/app/ngspice/install_min/bin/ngspice -p 
    ngspice 1 -> hello
    ngspice 2 -> world
    ngspice 3 -> ngspice-44.2 done

Behavior with libreadline::

    $ echo -e "echo hello\necho world\nquit" | /home/app/ngspice/install_readline/bin/ngspice -p 
    ngspice 1 -> echo hello
    hello
    ngspice 2 -> echo world
    world
    ngspice 3 -> quit
    ngspice-44.2 done

Behavior with libedit::

    $ echo -e "echo hello\necho world\nquit" | /home/app/ngspice/install_editline/bin/ngspice -p 
    hello
    world
    ngspice-44.2 done

These differences are addressed in ordec/sim2/ngspice.py.

TODO: Add automated testing for this in container, such as::

    PATH=/home/app/ngspice/install_min/bin:$PATH_ORIG pytest tests/test_sim2.py
    PATH=/home/app/ngspice/install_readline/bin:$PATH_ORIG pytest tests/test_sim2.py
    PATH=/home/app/ngspice/install_editline/bin:$PATH_ORIG pytest tests/test_sim2.py
