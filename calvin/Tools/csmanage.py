#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2015 Ericsson AB
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import argparse
import os
import glob
import shutil
import json
from calvin.csparser.parser import calvin_parser
from calvin.csparser.checker import check
from calvin.actorstore import store
from calvin.utilities import certificate
from calvin.utilities import certificate_authority
from calvin.utilities import code_signer
from calvin.utilities.utils import get_home
from calvin.utilities.attribute_resolver import AttributeResolver
from calvin.utilities import calvinuuid
from calvin.actorstore.store import ActorStore


def check_script(file):
    try:
        with open(file, 'r') as source:
            source_text = source.read()
    except:
        return {}, [{'reason': 'File not found', 'line': 0, 'col': 0}], []
    # Steps taken:
    # 1) parser .calvin file -> IR. May produce syntax errors/warnings
    # 2) checker IR -> IR. May produce syntax errors/warnings
    ir, errors, warnings = calvin_parser(source_text, file)
    # If there were errors during parsing no IR will be generated
    if not errors:
        c_errors, c_warnings = check(ir)
        errors.extend(c_errors)
        warnings.extend(c_warnings)
    return ir, errors, warnings


def install_component(namespace, name, definition, overwrite):
    astore = store.ActorStore()
    return astore.add_component(namespace, name, definition, overwrite)


def parse_args():
    long_desc = """Manage the host's actor store and credentials"""
    # top level arguments
    argparser = argparse.ArgumentParser(description=long_desc)
    cmdparsers = argparser.add_subparsers(help="command help")

    # parser for install cmd
    install_commands = ['component', 'actor']

    cmd_install = cmdparsers.add_parser('install', help='install components and actors')
    cmd_install.add_argument('cmd', metavar='<command>', choices=install_commands, type=str,
                           help="one of %s" % ", ".join(install_commands))
    cmd_install.add_argument('--force', dest='force', action='store_true',
                           help='overwrite components or actor that exists at destination')
    cmd_install.add_argument('--org', metavar='<name>', dest='org', type=str,
                           help='Code Signer org name used, assumes default location when no calvin.conf')
    cmd_install.add_argument('--namespace', metavar='<ns.sub-ns>', type=str, required=True,
                           help='namespace to install actor or components under')
    aargs = cmd_install.add_argument_group("actor")
    aargs.add_argument('--actor', metavar='<path>', action='append', default=[], required=True,
                           help='actor file to install, can be repeated')
    gargs = cmd_install.add_argument_group("component")
    gargs.add_argument('--script', metavar='<path>', type=str, required=True,
                           help='script file with component definitions')
    whichcomp = gargs.add_mutually_exclusive_group(required=True)
    whichcomp.add_argument('--all', dest='component', action='store_const', const=[],
                       help='install all components found in script')
    whichcomp.add_argument('--component', metavar='<component>', type=str, nargs='+',
                       help='name of component(s) to install')
    gargs.add_argument('--issue-fmt', dest='fmt', type=str,
                           default='{issue_type}: {reason} {script} [{line}:{col}]',
                           help='custom format for issue reporting.')

    cmd_install.set_defaults(func=manage_install)



    ######################
    # parser for CS cmd
    ######################
    cs_commands = ['create', 'remove', 'export', 'sign']

    cs_parser = cmdparsers.add_parser('cs', help='manage CS')
    cs_parser = cs_parser.add_subparsers(help='sub-command help', dest='cs_subparser_name')

    #parser for cs create cmd
    cmd_cs_create = cs_parser.add_parser('create', help='Create a Certificate Signer (CS) for signing application and actors')
    #required arguments
    cmd_cs_create.add_argument('name', metavar='<name>', type=str,
                           help='Name of the code signer')
    #optional arguments
    cmd_cs_create.add_argument('--dir', metavar='<dir>', type=str,
                           help='Path to create the cs at')
    cmd_cs_create.add_argument('--force', dest='force', action='store_true',
                           help='overwrite file that exists at destination')

    cmd_cs_create.set_defaults(func=manage_cs_create)

    #parser for cs export cmd
    cmd_cs_export = cs_parser.add_parser('export', help='Export the CS\'s certificate as <fingerprint>.0 in pem format')
    #required arguments
    cmd_cs_export.add_argument('name', metavar='<name>', type=str,
                           help='Name of the code signer')
    cmd_cs_export.add_argument('path', metavar='<path>', type=str,
                           help='export to directory')
    #optional arguments
    cmd_cs_export.add_argument('--force', dest='force', action='store_true',
                           help='overwrite file that exists at destination')
    cmd_cs_export.add_argument('--dir', metavar='<dir>', type=str, default="",
                           help='security directory, defaults to ~/.calvin/security')

    cmd_cs_export.set_defaults(func=manage_cs_export)


    #parser for cs sign cmd
    cmd_cs_sign = cs_parser.add_parser('sign', help='Sign an application or actor')
    #required arguments
    cmd_cs_sign.add_argument('name', metavar='<name>', type=str,
                           help='name of the code signer to use when signing the application/actor')
#    cmd_cs_sign.add_argument('file', metavar='<file>', type=str,
    cmd_cs_sign.add_argument('file', metavar='<file>', action='append', default=[],
                           help='path to file to be signed')
    #optional arguments
    cmd_cs_sign.add_argument('--force', dest='force', action='store_true',
                           help='overwrite file that exists at destination')
    cmd_cs_sign.add_argument('--dir', metavar='<dir>', type=str, default="",
                           help='security directory, defaults to ~/.calvin/security')
    cmd_cs_sign.add_argument('--nsfile', metavar='<ns.sub-ns.actor>', action='append', default=[],
                           help='namespaced store path to actor or components, can be repeated')
 
    cmd_cs_sign.set_defaults(func=manage_cs_sign)

    ######################
    # parser for CA cmd
    ######################
    ca_commands = ['create', 'remove', 'export', 'signCSR']

    ca_parser = cmdparsers.add_parser('ca', help='manage CA')
    ca_parser = ca_parser.add_subparsers(help='sub-command help', dest='ca_subparser_name')

    #parser for CA create cmd
    cmd_ca_create = ca_parser.add_parser('create', help='Create a Certificate Authority (CA) for transport security')
    #required arguments
    cmd_ca_create.add_argument('domain', metavar='<domain>', type=str,
                           help='Name of the domain')
    #optional arguments
    cmd_ca_create.add_argument('--dir', metavar='<dir>', type=str,
                           help='Path to create the CA at')
    cmd_ca_create.add_argument('--force', dest='force', action='store_true',
                           help='overwrite file that exists at destination')

    cmd_ca_create.set_defaults(func=manage_ca_create)

    #parser for CA export cmd
    cmd_ca_export = ca_parser.add_parser('export', help='Export the CA\'s root certificate as <fingerprint>.0 in pem format')
    #required arguments
    cmd_ca_export.add_argument('domain', metavar='<domain>', type=str,
                           help='Name of the domain')
    cmd_ca_export.add_argument('path', metavar='<path>', type=str,
                           help='export to directory')
    #optional arguments
    cmd_ca_export.add_argument('--force', dest='force', action='store_true',
                           help='overwrite file that exists at destination')
    cmd_ca_export.add_argument('--dir', metavar='<dir>', type=str, default="",
                           help='security directory, defaults to ~/.calvin/security')

    cmd_ca_export.set_defaults(func=manage_ca_export)


    #parser for CA signCSR cmd
    cmd_ca_sign_csr = ca_parser.add_parser('signCSR', help='Sign a Certificate Signing Request and create certificate')
    #required arguments
    cmd_ca_sign_csr.add_argument('domain', metavar='<domain>', type=str,
                           help='name of domain for which the certificate is to be signed')
    cmd_ca_sign_csr.add_argument('CSR', metavar='<CSR>', type=str,
                           help='path to CSR to be signed')
    #optional arguments
    cmd_ca_sign_csr.add_argument('--force', dest='force', action='store_true',
                           help='overwrite file that exists at destination')
    cmd_ca_sign_csr.add_argument('--dir', metavar='<dir>', type=str, default="",
                           help='security directory, defaults to ~/.calvin/security')

    cmd_ca_sign_csr.set_defaults(func=manage_ca_sign_csr)

    ######################
    # parser for runtime cmd
    ######################
    runtime_commands = ['create', 'export', 'import']

    runtime_parser = cmdparsers.add_parser('runtime', help='manage runtime certificates and keys')
    runtime_parser = runtime_parser.add_subparsers(help='sub-command help', dest='runtime_subparser_name')

    #parser for runtime create cmd
    cmd_runtime_create = runtime_parser.add_parser('create', help='Create a runtime keypair and a Certificate Signing Request (CSR) for transport security')
    #required arguments
    cmd_runtime_create.add_argument('domain', metavar='<domain>', type=str,
                           help='Name of the domain')
    cmd_runtime_create.add_argument('attr', metavar='<attr>', type=str,
                           help='runtime attributes, at least name and organization of node_name needs to be supplied, e.g. \'{"indexed_public:{"node_name":{"name":"testName", "organization":"testOrg"}}}\'')
    #optional arguments
    cmd_runtime_create.add_argument('--dir', metavar='<dir>', type=str,
                           help='Path to create the runtime at')
    cmd_runtime_create.add_argument('--force', dest='force', action='store_true',
                           help='overwrite file that exists at destination')

    cmd_runtime_create.set_defaults(func=manage_runtime_create)


    #parser for runtime export cmd
    cmd_runtime_export = runtime_parser.add_parser('export', help='exports a CSR in pem format from a generated key pair')
    #required arguments
    cmd_runtime_export.add_argument('dir', metavar='<dir>', type=str,
                           help='export to directory')
    #optional arguments
    cmd_runtime_export.add_argument('--force', dest='force', action='store_true',
                           help='overwrite file that exists at destination')

    cmd_runtime_export.set_defaults(func=manage_runtime_export)


    #parser for runtime import cmd
    cmd_runtime_import = runtime_parser.add_parser('import', help='import a runtime certificate signed by the CA (generated from the CSR)')
    #required arguments
    cmd_runtime_import.add_argument('certificate', metavar='<certificate>', type=str,
                           help='a path to a CA signed certificate for the runtime')
    #optional arguments
    cmd_runtime_import.add_argument('--force', dest='force', action='store_true',
                           help='overwrite file that exists at destination')
    cmd_runtime_import.add_argument('--dir', metavar='<directory>', type=str, default="",
                           help='security directory, defaults to ~/.calvin/security')

    cmd_runtime_import.set_defaults(func=manage_runtime_import)

    # parser for trust cmd
    trust_commands = ['trust']

    cmd_runtime_trust = runtime_parser.add_parser('trust', help='manage the runtime\'s trusted certificates')
    #required arguments
    cmd_runtime_trust.add_argument('node_name', metavar='<node_name>', type=str,
                           help='name of the runtime for which the CA certificate is to be imported')
    cmd_runtime_trust.add_argument('cacert', metavar='<cacert>', type=str,
                           help='path to CA certificate to trust')
    cmd_runtime_trust.add_argument('type', metavar='<type>', type=str,
                           help='flag indicating if the certificate is to be used for verification of application/actor signatures or as root of trust for transport security. Accepted values are {"transport","code_authenticity"}')
    #optional arguments
    cmd_runtime_trust.add_argument('--dir', metavar='<directory>', type=str, default="",
                           help='security directory, defaults to ~/.calvin/security')

    cmd_runtime_trust.set_defaults(func=manage_runtime_trust)




    return argparser.parse_args()

def manage_install(args):
    def report_issues(issues, issue_type, file=''):
        sorted_issues = sorted(issues, key=lambda k: k.get('line', 0))
        for issue in sorted_issues:
            sys.stderr.write(args.fmt.format(script=file, issue_type=issue_type, **issue) + '\n')

    ir, errors, warnings = check_script(args.script)
    if warnings:
        report_issues(warnings, 'Warning', args.script)
    if errors:
        report_issues(errors, 'Error', args.script)
        return 1

    errors = []
    for comp_name, comp_def in ir['components'].items():
        if args.component and comp_name not in args.component:
            continue
        ok = install_component(args.namespace, comp_name, comp_def, args.overwrite)
        if not ok:
            errors.append({'reason': 'Failed to install "{0}"'.format(comp_name),
                          'line': comp_def['dbg_line'], 'col': 0})

    if errors:
        report_issues(errors, 'Error', args.script)
        return 1


################################
# manage Certificate Authority
################################

def manage_ca_create(args):
    if not args.domain:
        raise Exception("No domain supplied")
    certificate_authority.CA(domain=args.domain, commonName=args.domain+"CA", security_dir=args.dir, force=args.force)

def manage_ca_remove(args):
    if not args.domain:
        raise Exception("No domain supplied")
    domaindir = os.path.join(args.dir, args.domain) if args.dir else None
    certificate.remove_domain(args.domain, domaindir)

def manage_ca_export(args):
    if not args.domain:
        raise Exception("No domain supplied")
    if not args.path:
        raise Exception("No out path supplied")
    ca = certificate_authority.CA(domain=args.domain, security_dir=args.dir, readonly=True)
    out_file = ca.export_ca_cert(args.path)
    print "exported to:" + out_file

def manage_ca_sign_csr(args):
    if args.domain and args.CSR:
        if not args.domain:
            raise Exception("No domain supplied")
        if not args.CSR:
            raise Exception("supply CSR path")
        exist = os.path.isfile(args.CSR)
        if not exist:
            raise Exception("The CSR path supplied is not an existing file")
        ca = certificate_authority.CA(domain=args.domain, security_dir=args.dir, force=args.force)
        ca.sign_csr(args.CSR)

######################
# manage Code Signer
######################

def manage_cs_create(args):
    if not args.name:
        raise Exception("No name of code signer supplied")
    code_signer.CS(organization=args.name, commonName=args.name+"CS", security_dir=args.dir, force=args.force)

def manage_cs_remove(args):
    if not args.name:
        raise Exception("No code signer name supplied")
    code_signer.remove_cs(args.nane, security_dir=args.dir)

def manage_cs_export(args):
    if not args.name:
        raise Exception("No code signer name supplied")
    if not args.path:
        raise Exception("No out path supplied")
    cs = code_signer.CS(organization=args.name, commonName=args.name+"CS", security_dir=args.dir, force=args.force)
    out_file = cs.export_cs_cert(args.path)
    print "exported to:" + out_file

def manage_cs_sign(args):
    if not args.name:
        raise Exception("No code signer name supplied")
    if not args.file:
        raise Exception("supply path to a file(s) to sign")
    cs = code_signer.CS(organization=args.name, commonName=args.name+"CS", security_dir=args.dir, force=args.force)
    # Collect files to sign
    files = []
    if args.file:
        for f in args.file:
            exist = os.path.isfile(f)
            if not exist:
                raise Exception("The file path supplied is not an existing file")
            files.extend(glob.glob(f))
    if args.nsfile:
        store = ActorStore()
        for m in args.nsfile:
            files.extend(store.actor_paths(m))
    # Filter out any files not *.calvin, *.py
    files = [f for f in files if f.endswith(('.calvin', '.py')) and not f.endswith('__init__.py')]
    if not files:
        raise Exception("No (*.calvin, *.py) files supplied")
    exceptions = []
    for f in files:
        try:
            cs.sign_file(f)
        except Exception as e:
            exceptions.append(e)
    for e in exceptions:
        print "Error {}".format(e)



######################
# manage runtime
######################
def manage_runtime_create(args):
    if args.domain:
        if not args.attr:
            raise Exception("No runtime attributes supplied")
        if not args.domain:
            raise Exception("No domain name supplied")
        attr = json.loads(args.attr)
        if not all (k in attr['indexed_public']['node_name'] for k in ("organization","name")):
            raise Exception("please supply name and organization of runtime")
        attributes=AttributeResolver(attr)
        node_name=attributes.get_node_name_as_str()
        nodeid = calvinuuid.uuid("NODE")
        print "CSR created at:" + certificate.new_runtime(node_name, args.domain, security_dir=args.dir, nodeid=nodeid)

def manage_runtime_export(args):
    raise Exception("Not yet implemented")

def manage_runtime_remove(args):
    if not args.domain:
        raise Exception("No domain supplied")
    domaindir = os.path.join(args.dir, args.domain) if args.dir else None
    certificate.remove_domain(args.domain, domaindir)

def manage_runtime_import(args):
    if not args.certificate:
        raise Exception("No certificate supplied")
    certificate.store_own_cert(certpath=args.certificate, security_dir=args.dir )

def manage_runtime_trust(args):
    if not args.cacert:
        raise Exception("No path to CA cert supplied")
    if not args.type:
        raise Exception("No type supplied")
    if not args.node_name:
        raise Exception("No runtime name supplied")

    if args.type=="transport":
        certificate.store_trusted_root_cert(args.cacert, "truststore_for_transport", security_dir=args.dir)
    elif args.type=="code_authenticity":
        certificate.store_trusted_root_cert(args.cacert, "truststore_for_signing", security_dir=args.dir)

def main():
    args = parse_args()

    try:
        args.func(args)
    except Exception as e:
        print "Error {}".format(e)

if __name__ == '__main__':
    sys.exit(main())
