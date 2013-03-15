#!/usr/bin/env python
# coding: utf-8
#
# Copyright (c) 2013, Torbjörn Lönnemark <tobbez@ryara.net>
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#

import argparse
import envoy
import ctypes.util
import os
import shutil
import errno
import stat

def ldd(path):
    r = envoy.run('ldd ' + path)
    if r.std_out.strip() == 'not a dynamic executable':
        return []
    lines = [l.strip().split(' ') for l in r.std_out.strip().split('\n')]
    lines = filter(lambda x: not x[0].startswith('linux-vdso.'), lines)


    libs = []
    for line in lines:
        if len(line) == 2:
            libs.append(line[0])
        else:
            libs.append(line[2])
    return libs

def deref_links(path):
    paths = [path]
    if os.path.islink(path):
        paths.append(os.path.realpath(path))
    return paths

def copy(src, dst):
    if os.path.exists(dst):
        return

    if os.path.islink(src):
        os.symlink(os.readlink(src), dst)
        #st = os.lstat(dst)
        os.lchown(dst, 0, 0)
    else:
        shutil.copy(src, dst)
        shutil.copystat(src, dst)
        os.chown(dst, 0, 0)

def touch(path):
    with file(path, 'a'):
        os.utime(path, None)

def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno == errno.EEXIST:
            pass
        else:
            raise

def mkchrdev(path, major, minor, mode = 0666):
    if not os.path.exists(path):
        os.mknod(os.path.join(path), mode | stat.S_IFCHR, os.makedev(major, minor))

def main():
    parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
            description='Helper for creating minimal LXC containers',
            epilog="""While it is allowed to specify both an fstab and an LXC configuration,
there is generally no reason to do so, since only one is needed.

If you need user capabilities, you need to supply at least libnsl and
libnss_compat (and/or others, if configured in nsswitch.conf).""")

    filesgroup = parser.add_mutually_exclusive_group(required=True)
    filesgroup.add_argument('--copy', '-c', type=str, help="copy specified programs and dependencies to the specified directory", metavar='DEST')
    filesgroup.add_argument('--make-mountpoints', '-m', type=str, help="create mount points for programs and dependencies in the specified directory", metavar='DEST')

    parser.add_argument('--fstab', '-f', type=argparse.FileType('a'), help="file to append fstab lines to")
    parser.add_argument('--lxc-conf', '-l', type=argparse.FileType('a'), help="file to append lxc-configuration mount entries to")

    parser.add_argument('--user-files', '-u', action='store_true', help="create user files (/etc/{passwd,group})")
    parser.add_argument('--inittab', '-i', action='store_true', help="create basic inittab")

    parser.add_argument('program', nargs='+', help="path to a program or library that should be included in the container")

    args = parser.parse_args()

    dest_dir = None
    if args.copy != None:
        dest_dir = args.copy
    
    if args.make_mountpoints != None:
        dest_dir = args.make_mountpoints

    dest_dir = os.path.abspath(dest_dir)

    files = []

    args.program += ['/sbin/init', '/sbin/shutdown']

    for p in args.program:
        files.append(p)
        files.extend(ldd(p))

    derefs = []
    for f in files:
        derefs.extend(deref_links(f))

    files.extend(derefs)

    files = list(set(files))

    mount_lines = []
    
    for f in files:
        dst_path = os.path.join(dest_dir, f[1:])
        mkdir_p(os.path.dirname(dst_path))
        if args.copy != None:
            copy(f, dst_path)
        elif args.make_mountpoints != None:
            touch(dst_path)

        mount_lines.append('{} {} none ro,bind 0 0\n'.format(f, dst_path))

    mkdir_p(os.path.join(dest_dir, 'dev/pts'))
    os.chmod(os.path.join(dest_dir, 'dev/pts'), 0755)

    mkdir_p(os.path.join(dest_dir, 'dev/shm'))
    os.chmod(os.path.join(dest_dir, 'dev/shm'), 01777)

    if not os.path.exists(os.path.join(dest_dir, 'dev/initctl')):
        os.mknod(os.path.join(dest_dir, 'dev/initctl'), 666 | stat.S_IFIFO)
    
    mkchrdev(os.path.join(dest_dir, 'dev/null'), 1, 3)
    mkchrdev(os.path.join(dest_dir, 'dev/zero'), 1, 5)
    mkchrdev(os.path.join(dest_dir, 'dev/random'), 1, 8)
    mkchrdev(os.path.join(dest_dir, 'dev/urandom'), 1, 9)
    mkchrdev(os.path.join(dest_dir, 'dev/tty'), 5, 0)
    mkchrdev(os.path.join(dest_dir, 'dev/console'), 5, 1, 0600)
    mkchrdev(os.path.join(dest_dir, 'dev/tty0'), 4, 0)
    mkchrdev(os.path.join(dest_dir, 'dev/tty1'), 4, 1)
    mkchrdev(os.path.join(dest_dir, 'dev/tty2'), 4, 2)
    mkchrdev(os.path.join(dest_dir, 'dev/tty3'), 4, 3)
    mkchrdev(os.path.join(dest_dir, 'dev/tty4'), 4, 4)
    mkchrdev(os.path.join(dest_dir, 'dev/full'), 1, 7)
    mkchrdev(os.path.join(dest_dir, 'dev/ptmx'), 5, 2)
    
    mkdir_p(os.path.join(dest_dir, 'proc'))

    if args.fstab != None:
        args.fstab.writelines(mount_lines)
        args.fstab.close()

    if args.lxc_conf != None:
        args.lxc_conf.writelines(['lxc.mount.entry=' + l for l in mount_lines])
        args.lxc_conf.close()

    if args.user_files:
        path = os.path.join(dest_dir, 'etc/')
        mkdir_p(path)

        passwd = os.path.join(path, 'passwd')
        if not os.path.exists(passwd):
            with file(passwd, 'w') as f:
                f.write('root:x:0:0:root:/root:/bin/sh\n')

        group = os.path.join(path, 'group')
        if not os.path.exists(group):
            with file(group, 'w') as f:
                f.write('root:x:0:root\n')

    if args.inittab:
        path = os.path.join(dest_dir, 'etc/')
        mkdir_p(path)

        inittab = os.path.join(path, 'inittab')
        if not os.path.exists(inittab):
            with file(inittab, 'w') as f:
                f.write('''id:3:initdefault:

rc0:0:wait:/etc/rc.stop.sh
rc3:3:once:/etc/rc.start.sh

# sshd:3:wait:/usr/sbin/sshd

# c1:3:respawn:/sbin/agetty -n -l /bin/sh 38400 tty1 linux

exit:12345:powerfail:/sbin/shutdown -t1 -h now''')


if __name__ == '__main__':
    main()
