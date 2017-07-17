#!/usr/bin/env python
#
# Copyright (c) 2014 The WebRTC project authors. All Rights Reserved.
#
# Use of this source code is governed by a BSD-style license
# that can be found in the LICENSE file in the root of the source
# tree. An additional intellectual property rights grant can be found
# in the file PATENTS.  All contributing project authors may
# be found in the AUTHORS file in the root of the source tree.

# This script is used to run GYP for WebRTC. It contains selected parts of the
# main function from the src/build/gyp_chromium.py file while other parts are
# reused to minimize code duplication.

import gc
import glob
import os
import sys
import pipes
import xml.etree.ElementTree as ET

script_dir = os.path.dirname(os.path.realpath(__file__))
checkout_root = os.path.abspath(os.path.join(script_dir, os.pardir, os.pardir))

sys.path.insert(0, os.path.join(checkout_root, 'build'))
import gyp_chromium
import gyp_helper
import vs_toolchain

sys.path.insert(0, os.path.join(checkout_root, 'tools', 'gyp', 'pylib'))
import gyp


def GetSupplementalFiles():
  """Returns a list of the supplemental files.

  A supplemental file is included in all GYP sources. Such files can be used to
  override default values.
  """
  # Can't use the one in gyp_chromium since the directory location of the root
  # is different.
  return glob.glob(os.path.join(checkout_root, '*', 'supplement.gypi'))

def fixVS2015Ninja():
  vs2015 = '14.0'

  if os.environ.get('GYP_GENERATORS') == 'ninja-winrt' and os.environ.get('VisualStudioVersion') == vs2015:
    vcpackagePath = os.path.join(os.environ.get('VCInstallDir'), 'vcpackages')
    if  'LIBPATH' in os.environ:
      os.environ['LIBPATH'] = os.environ['LIBPATH'] + vcpackagePath+';'
    else:
      os.environ.update({'LIBPATH':  vcpackagePath+';'})

    #In the VS2015+WinSDK10 environment, the windsdk include path depends on the installed sdk minor verion
    #ex.: 10.0.3000.0. we will need to find it from SDKManifest.xml
    sdfManifestFile = os.environ.get('UniversalCRTSdkDir') + 'SDKManifest.xml';

    sdkVersion = None;

    xmlRoot = ET.parse(sdfManifestFile).getroot()
    for fileListNode in xmlRoot.iter('FileList'):
      if fileListNode.get('PlatformIdentity'):
        sdkVersion = fileListNode.get('PlatformIdentity');
        verPos = sdkVersion.find('Version=')
        sdkVersion = sdkVersion[verPos+8:]
        break;

    if sdkVersion:
      #contruct WindowsSDK_IncludePath used by VS2015
      WindowsSDK_IncludePath = "{0}include\{1}\shared;{0}include\{1}\um;{0}include\{1}\winrt;".format(os.environ.get('UniversalCRTSdkDir'),sdkVersion)
      UCRT_PATH = "{}include\ucrt;".format(os.environ.get('UniversalCRTSdkDir'))
      os.environ.update({'VS_EXTRA_INCLUDES': UCRT_PATH + WindowsSDK_IncludePath})
      #Todo: for ninja+vs2015+win10, we only support x86 for now
      WindowsSDK_lIBPath = "{0}Lib\{1}\um\\x86;".format(os.environ.get('UniversalCRTSdkDir'),sdkVersion)
      os.environ['LIB'] = WindowsSDK_lIBPath + os.environ['LIB']  

def main():
  # Disabling garbage collection saves about 5% processing time. Since this is a
  # short-lived process it's not a problem.
  gc.disable()

  args = sys.argv[1:]

  if int(os.environ.get('GYP_CHROMIUM_NO_ACTION', 0)):
    print 'Skipping gyp_webrtc.py due to GYP_CHROMIUM_NO_ACTION env var.'
    sys.exit(0)

  if 'SKIP_WEBRTC_GYP_ENV' not in os.environ:
    # Update the environment based on webrtc.gyp_env.
    gyp_env_path = os.path.join(os.path.dirname(checkout_root),
                                'webrtc.gyp_env')
    gyp_helper.apply_gyp_environment_from_file(gyp_env_path)

  # This could give false positives since it doesn't actually do real option
  # parsing.  Oh well.
  gyp_file_specified = False
  for arg in args:
    if arg.endswith('.gyp'):
      gyp_file_specified = True
      break

  # If we didn't get a file, assume 'all.gyp' in the root of the checkout.
  if not gyp_file_specified:
    # Because of a bug in gyp, simply adding the abspath to all.gyp doesn't
    # work, but chdir'ing and adding the relative path does. Spooky :/
    os.chdir(checkout_root)
    args.append('all.gyp')

  # There shouldn't be a circular dependency relationship between .gyp files,
  args.append('--no-circular-check')

  # Default to ninja unless GYP_GENERATORS is set.
  if not os.environ.get('GYP_GENERATORS'):
    os.environ['GYP_GENERATORS'] = 'ninja'

  fixVS2015Ninja()

  # Enable check for missing sources in GYP files on Windows.
  if sys.platform.startswith('win'):
    gyp_generator_flags = os.getenv('GYP_GENERATOR_FLAGS', '')
    if not 'msvs_error_on_missing_sources' in gyp_generator_flags:
      os.environ['GYP_GENERATOR_FLAGS'] = (
          gyp_generator_flags + ' msvs_error_on_missing_sources=1')

  vs2013_runtime_dll_dirs = None
  if int(os.environ.get('DEPOT_TOOLS_WIN_TOOLCHAIN', '1')):
    vs2013_runtime_dll_dirs = vs_toolchain.SetEnvironmentAndGetRuntimeDllDirs()
  else:
    gyp_defines_dict = gyp.NameValueListToDict(gyp.ShlexEnv('GYP_DEFINES'))
    winSdkDir = os.environ.get('UniversalCRTSdkDir')
    if winSdkDir != None:
        gyp_defines_dict['windows_sdk_path'] = winSdkDir
        os.environ['GYP_DEFINES'] = ' '.join('%s=%s' % (k, pipes.quote(str(v)))
            for k, v in gyp_defines_dict.iteritems())

  # Enforce gyp syntax checking. This adds about 20% execution time.
  args.append('--check')

  supplemental_includes = GetSupplementalFiles()
  gyp_vars = gyp_chromium.GetGypVars(supplemental_includes)

  # Automatically turn on crosscompile support for platforms that need it.
  if all(('ninja' in os.environ.get('GYP_GENERATORS', ''),
          gyp_vars.get('OS') in ['android', 'ios'],
          'GYP_CROSSCOMPILE' not in os.environ)):
    os.environ['GYP_CROSSCOMPILE'] = '1'

  args.extend(['-I' + i for i in
               gyp_chromium.additional_include_files(supplemental_includes,
                                                     args)])

  # Set the gyp depth variable to the root of the checkout.
  args.append('--depth=' + os.path.relpath(checkout_root))

  print 'Updating projects from gyp files...'
  sys.stdout.flush()

  # Off we go...
  gyp_rc = gyp.main(args)

  if vs2013_runtime_dll_dirs:
    # pylint: disable=unpacking-non-sequence
    x64_runtime, x86_runtime = vs2013_runtime_dll_dirs
    vs_toolchain.CopyVsRuntimeDlls(
        os.path.join(checkout_root, gyp_chromium.GetOutputDirectory()),
        (x86_runtime, x64_runtime))

  sys.exit(gyp_rc)


if __name__ == '__main__':
  sys.exit(main())
