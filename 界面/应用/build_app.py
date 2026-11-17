"""Build the local Dock launcher using installed macOS tools; no downloads."""
import plistlib
from pathlib import Path
import subprocess
home=Path(__file__).resolve().parent
bundle=home/'Soundlog.app';contents=bundle/'Contents';mac=contents/'MacOS';resources=contents/'Resources'
mac.mkdir(parents=True,exist_ok=True);resources.mkdir(exist_ok=True)
subprocess.run(['xcrun','swiftc',str(home/'Soundlog.swift'),'-o',str(mac/'Soundlog'),'-framework','Cocoa','-framework','WebKit'],check=True)
with (contents/'Info.plist').open('wb') as f:
 plistlib.dump(dict(CFBundleExecutable='Soundlog',CFBundleIdentifier='local.soundlog.desktop',CFBundleName='Soundlog',CFBundleDisplayName='Soundlog',CFBundlePackageType='APPL',CFBundleShortVersionString='1.0',CFBundleVersion='1',CFBundleIconFile='Soundlog',NSHighResolutionCapable=True),f)
iconset=resources/'Soundlog.iconset';iconset.mkdir(exist_ok=True)
source=resources/'icon.png';subprocess.run([str(mac/'Soundlog'),'--icon',str(source)],check=True)
for n in [16,32,128,256,512]:
 for scale in [1,2]:
  subprocess.run(['sips','-z',str(n*scale),str(n*scale),str(source),'--out',str(iconset/f'icon_{n}x{n}{"@2x" if scale==2 else ""}.png')],check=True,stdout=subprocess.DEVNULL)
subprocess.run(['iconutil','-c','icns',str(iconset),'-o',str(resources/'Soundlog.icns')],check=True)
print(bundle)
