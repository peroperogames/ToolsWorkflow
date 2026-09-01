#!/usr/bin/expect -f
set timeout 10
set registry [lindex $argv 0]
set username [lindex $argv 1]
set password [lindex $argv 2]
set email [lindex $argv 3]

spawn npm login --registry $registry
expect "Username:"
send "$username\r"
expect "Password:"
send "$password\r"
expect "Email: (this IS public)"
send "$email\r"
expect eof
