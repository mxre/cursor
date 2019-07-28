#!/usr/bin/env python3
#
# make cursor theme
#
# Released under the GNU General Public License, version 2.
# Email Lee Braiden of Digital Unleashed at lee.b@digitalunleashed.com
# with any questions, suggestions, patches, or general uncertainties
# regarding this software.

usageMsg = """You need to add a layer called "slices", and draw rectangles on it to represent the areas that should be saved as slices.  It helps when drawing these rectangles if you make them translucent.

The names (inkscape id) will be reflected in the slice filenames.
"""

# Inkscape provides dimensions for the slice boxes. All slices need to be of the same size.
# Inkscape is renders once each size and with PIL/Pillow's crop we cut the correct cursor
# Mark cursor hotspot with a dot (x,y position counts; not the center), and name it "id", with a 'hotspot.' prefix
# xcursorgen is provided with the scaled and cropped pngs for each cursor and the corresponding hotspot information
# names.txt (real name is the first in each line, link names come after that, spaces seperated) generates symlinks for the theme

# Layers: hotspots (should be top), slices (name for cursor slices)
# shadow filter must be named "drop_shadow" (id) and all cursors having a shadow must be grouped labeld "shadow" (inkscape:label)

import argparse

args_parser = argparse.ArgumentParser("Convert SVG to cursor theme")
args_parser.add_argument('-d','--debug',action='store_true',dest='debug',help='Enable extra debugging info')
args_parser.add_argument('-v','--verbose',action='store_true',dest='verbose',help='Enable info output')
args_parser.add_argument('-t','--test',action='store_true',dest='test',help='Keep intermediary data files')
args_parser.add_argument('-c','--clean',action='store_true',dest='clean',help='Delete every generated file')
args_parser.add_argument('-f','--force',action='store_true',dest='force',help='Overwrite existing cursor theme')
args_parser.add_argument('-n','--name',action='store',dest='theme_name',help='Name of the new cursor theme')
args_parser.add_argument('input_file',nargs=1,help='Input SVG file')
args_parser.add_argument('-o','--out',action='store',dest='output_directory',help='Cursor theme output directory')
args_parser.add_argument('-a','--anicur',action='store_true',dest='anicur',help='Use anicursorgen.py to generate a Windows cursor set')
args_parser.add_argument('--sizes',action='store',dest='sizes',help='Override cursor sizes, sorted comma seprated list of values (default: 24,32,48,64,96)')
args_parser.add_argument('--fps',action='store',dest='fps',help='Override FPS for animated cursors (default: 16.6)')
args_parser.add_argument('-s', '--shadow',action='store_true',dest='shadow',help='Render cursor drop shadow from SVG')

# generated cursor sizes
sizes = [ 24, 32, 48, 64, 96 ]

fps = 16.66666

# synonym database for X11 cursor
icon_names_database = 'names.txt'

# directory for generated hotspots includes for xcursorgen
hotspots_directory = 'hotspots'
# directory for generated cursor pngs
pngs_directory = 'pngs'

# executable for rsvg-convert
rsvg_convert_path = 'rsvg-convert'
# executable for xcursorgen
xcursorgen_path = 'xcursorgen'
# executable for ffmpeg (used to generated animated previews in -t mode)
ffmpeg_path = 'ffmpeg'
# animated preview format (for ffmpeg) and file suffix
animated_preview_format = { 'ffmpeg_format': 'apng', 'suffix': 'apng'}

from xml.sax import saxutils, make_parser, SAXParseException, handler, xmlreader
from xml.sax.handler import feature_namespaces
import os, sys, stat, shutil
import subprocess, gzip, re
import PIL.Image
from tempfile import TemporaryFile

if __name__ == '__main__':
	# parse command line into arguments and options
	options = args_parser.parse_args()

def dbg(msg):
	if options.debug:
		print(msg, file=sys.stderr)

def warn(msg):
	print("WARNING: " + msg, file=sys.stderr)

def info(msg):
	if options.verbose:
		print(msg, file=sys.stdout)

def fatalError(msg):
	print("FATAL ERROR: " + msg, file=sys.stderr)
	sys.exit(20)

class SVGRect:
	"""Manages a simple rectangular area, along with certain attributes such as a name"""

	def __init__(self, name=None):
		self.slice = (0,0,0,0)
		self.hotspot = (0,0)
		self.name = name
		dbg("New SVGRect: ({})".format(name))
	
	def cropFromTemplate(self, image, size, pngs_directory):
		""" Crop this rect from a PNG and saves under its name in `pngs_directory`/`size`/`slice_name`.png """

		scale = size / round(self.slice[2])
		x = round(self.slice[0] * scale)
		y = round(self.slice[1] * scale)
		w = round(self.slice[2] * scale)
		h = round(self.slice[3] * scale)
		dbg("crop: {} {} ({},{},{},{})".format(self.name, size, x, y, x + w, y + h))
		img = image.crop((x, y, x + w, y + h))
		img.save('{opath}/{size}/{slice}.png'.format(size=size, opath=pngs_directory, slice=self.name))

	def writeCursorConfig(self, pngs_directory, hotspots_directory):
		"""
		write xcursorgen input file

		Expects pngs in `pngs_directory`/`size`/`slice_name`.png 
		and frames for animated cursor must end with `_nnnn` (where `nnnn`) is the
		positive frame number starting with 1

		A file named `hotspots_directory`/`slice_name`.in will be created
		"""

		(sliceName, frame) = self.get_animated_cursor_name()

		dbg("xcursor.in: {} frame {}".format(sliceName, frame))
		
		if frame == -1 or frame == 1:
			openmode = 'w'
		else:
			openmode = 'a'
		if frame == -1:
			delay = ''
		else:
			delay = ' {}'.format(round(1000.0 / fps))

		with open("{}/{}.in".format(hotspots_directory, sliceName), openmode) as f:
			for size in sizes:
				scale = size / round(self.slice[2])
				x = round(self.hotspot[0] * scale)
				y = round(self.hotspot[1] * scale)
				line = '{size} {x} {y} {size}/{name}.png{delay}'.format(
					size=size, x=x, y=y, name=self.name, delay=delay)
				dbg(line)
				f.write(line + '\n')
	
	def get_animated_cursor_name(self):
		sliceName = self.name
		frame = -1

		if sliceName[-5:].startswith('_'):
			try:
				frame = int(sliceName[-4:])
				sliceName = sliceName[:-5]
			except ValueError:
				pass
		return (sliceName, frame)

class SVGHandler(handler.ContentHandler):
	"""Base class for SVG document"""

	def __init__(self):
		self.width = 0
		self.height = 0
		self.title = None
		self._content = None

	def writeThemeDescription(self, output_directory=None):
		if output_directory is None:
			output_directory = self.title
		with open('{}/index.theme'.format(output_directory), "w") as f:
			f.write('[Icon Theme]\n')
			f.write('Name="{}"\n'.format(self.title))
	
	def linkCursorNames(self, names, output_directory=None):
		""" create symlinks in cursor theme directory accoring to cursor alias database """

		if output_directory is None:
			output_directory = self.title
		dirfd = os.open('{}/cursors'.format(output_directory), os.O_DIRECTORY)
		try:
			with open(names) as f:
				for l in f.readlines():
					if l.startswith('#'):
						continue
					a = l.rstrip().split(' ')
					try:
						if stat.S_ISREG(os.lstat(a[0], dir_fd=dirfd).st_mode):
							for target in a[1:]:
								try:
									os.remove(target, dir_fd=dirfd)
								except FileNotFoundError:
									pass
								dbg("ln -s {} {}".format(a[0], target))
								os.symlink(a[0], target, dir_fd=dirfd)
					except FileNotFoundError:
						pass
		finally:
			os.close(dirfd)

	def _isFloat(self, stringVal):
		try:
			return (float(stringVal), True)[1]
		except (ValueError, TypeError):
			return False

	def parseCoordinates(self, val):
		"""Strips the units from a coordinate, and returns just the value in pixles"""

		if val.endswith('px'):
			val = float(val.rstrip('px'))
		elif val.endswith('pt'):
			fatalError("Only px are supported as a unit")
		elif val.endswith('cm'):
			fatalError("Only px are supported as a unit")
		elif val.endswith('mm'):
			fatalError("Only px are supported as a unit")
		elif val.endswith('in'):
			fatalError("Only px are supported as a unit")
		elif val.endswith('%'):
			fatalError("Only px are supported as a unit")
		elif self._isFloat(val):
			val = float(val)
		else:
			fatalError("Coordinate value {} has unrecognised units. Only px supported.".format(val))
		return val

	def characters(self, c):
		""" Callback to read CDATA """
	
		if self._content is not None:
			self._content += c

	def startElement_svg(self, name, attrs):
		"""Callback hook which handles the start of an svg image"""

		dbg('startElement_svg called')
		width = attrs.get('width', None)
		height = attrs.get('height', None)
		self.width = self.parseCoordinates(width)
		self.height = self.parseCoordinates(height)

	def startElement_title(self, name, attrs):
		"""Callback hook to get document title"""

		dbg('startElement_title called')
		self._content = ""

	def endElement_title(self, name):
		dbg('endElement_title called')
		self.title = self._content.strip()
		self._content = None

	def endElement(self, name):
		"""General callback for the end of a tag"""

		dbg('Ending element "{}"'.format(name))

class SVGLayerHandler(SVGHandler):
	"""
	Parse an SVG file, extracing names for slicing rectangles from a "slices" layer
	and hold information mined by inkscape
	"""

	def __init__(self, svgFilename):
		SVGHandler.__init__(self)
		self.svgFilename = svgFilename
		# read by inkscape
		self.size = None
		self.file = TemporaryFile(mode='w+b')

		# named slices bounding box will be added later by inkscape
		self.svg_rects = {}
		self.slices_hidden = False
		self.hotspots_hidden = False

		self._layer_nests = 0
		self._layer_hotspots = 0
		self._translate = (0,0)
		self._name = None
		self._re_translate = re.compile(r'translate\((-?[0-9]+(?:\.[0-9]+)?)[, ](-?[0-9]+(?:\.[0-9]+)?)\)')
		# run parser
		self._filter_svg(self._openFile(), self.file)
		self.file.seek(0)
		self._runParser()
		
	def _openFile(self):
		# open svg and compressed svgz alike
		suffix = os.path.splitext(svgFilename)[1]
		if suffix == '.svg':
			return open(svgFilename, 'r', encoding='utf8')
		elif suffix in [ '.svgz', '.gz' ]:
			return gzip.open(svgFilename, 'r', encoding='utf8')
		else:
			fatalError("Unknown file extension: {}".format(suffix))

	def _filter_svg(self, input, output):
		output_gen = saxutils.XMLGenerator(output)
		parser = make_parser()
		mode = ""
		if options.shadow:
			mode += "shadows,"
		filter = SVGFilter(parser, output_gen, mode)
		filter.setFeature(handler.feature_namespaces, False)
		filter.setErrorHandler(handler.ErrorHandler())
		filter.parse(input)
		del filter
		del parser
		del output_gen

	def _runParser(self):
		xmlParser = make_parser()
		xmlParser.setFeature(feature_namespaces, 0)

		# setup XML Parser with an SVGLayerHandler class as a callback parser ####
		xmlParser.setContentHandler(self)

		try:
			xmlParser.parse(os.fdopen(self.file.fileno(), 'r', closefd=False))
		except SAXParseException as e:
			fatalError("Error parsing SVG file '{}': {},{}: {}.  If you're seeing this within inkscape, it probably indicates a bug that should be reported.".format(
				self.svgFilename, e.getLineNumber(), e.getColumnNumber(), e.getMessage()))
		del xmlParser

	def _isHidden(self, attrs):
		try:
			return attrs['display'] == 'none'
		except KeyError:
			try:
				return 'display:none' in attrs['style']
			except KeyError:
				False	

	def _inSlicesLayer(self):
		return (self._layer_nests >= 1)

	def _inHotspotsLayer(self):
		return (self._layer_hotspots) >= 1

	def _add(self, rect):
		"""Adds the given rect to the list of rectangles successfully parsed"""

		self.svg_rects[rect.name] = rect

	def _startElement_layer(self, name, attrs):
		"""
		Callback hook for parsing layer elements

		Checks to see if we're starting to parse a slices layer, and sets the appropriate flags.
		Otherwise, the layer will simply be ignored.
		"""

		try:
			dbg("found layer: name='{}'".format(attrs['inkscape:label']))
		except KeyError:
			dbg("found layer: name='{}'".format(attrs['id']))

		if attrs.get('inkscape:groupmode', None) == 'layer':
			if self._inSlicesLayer() or attrs['inkscape:label'] == 'slices':
				self._layer_nests += 1
			elif self._inHotspotsLayer() or attrs['inkscape:label'] == 'hotspots':
				self._layer_hotspots += 1

			if attrs['inkscape:label'] == 'slices':
				self.slices_hidden = self._isHidden(attrs)
				try:
					m = self._re_translate.match(attrs['transform'])
					self._translate = (float(m.group(1)), float(m.group(2)))
					dbg(self._translate)
				except (AttributeError, KeyError) as e:
					self._translate = (0,0)
					dbg(e)
			elif attrs['inkscape:label'] == 'hotspots':
				self.hotspots_hidden = self._isHidden(attrs)
				try:
					m = self._re_translate.match(attrs['transform'])
					self._translate = (float(m.group(1)), float(m.group(2)))
					dbg(self._translate)
				except (AttributeError, KeyError) as e:
					self._translate = (0,0)
					dbg(e)

	def _endElement_layer(self, name):
		"""
		Callback for leaving a layer in the SVG file

		Just undoes any flags set previously.
		"""

		dbg("leaving layer: name='{}'".format(name))
		if self._inSlicesLayer():
			self._layer_nests -= 1
			for i in self.svg_rects.values():
				i.slice = (
					(i.slice[0] + self._translate[0]) * 3.7795,
					(i.slice[1] + self._translate[1]) * 3.7795,
					i.slice[2] * 3.7795,
					i.slice[3] * 3.7795)
				if self.size is None:
					self.size = round(i.slice[2])
				dbg("{0} ({1[0]}, {1[1]}, {1[2]}, {1[3]}) ({2[0]}, {1[1]})".format(i.name, i.slice, self._translate))
		if self._inHotspotsLayer():
			self._layer_hotspots -= 1
			for i in self.svg_rects.values():
				dbg("hotspot {0} ({1[0]}, {1[1]})".format(i.name, i.hotspot))
				i.hotspot = (
					(i.hotspot[0] + self._translate[0] - 0.1) * 3.7795 - i.slice[0] ,
					(i.hotspot[1] + self._translate[1] - 0.1) * 3.7795 - i.slice[1])
				dbg("hotspot {0} ({1[0]}, {1[1]}) ({2[0]}, {2[1]})".format(i.name, i.hotspot, self._translate ))

	def _startElement_rect(self, name, attrs):
		"""
		Callback for parsing an SVG rectangle

		Checks if we're currently in a special "slices" layer using flags set by startElement_layer().
		If we are, the current rectangle is considered to be a slice, and is added to the list of parsed
		rectangles.  Otherwise, it will be ignored.
		"""

		if self._inSlicesLayer():
			try:
				name = attrs['inkscape:label']
			except KeyError:
				name = attrs['id']
			rect = SVGRect(name)
			rect.slice = (
				float(attrs['x']),
				float(attrs['y']),
				float(attrs['width']),
				float(attrs['height']))
			self._add(rect)

	def _startElement_circle(self, name, attrs):
		"""
		Callback for parsing an SVG circle

		Checks if we're currently in a special "hotspots" layer using flags set by startElement_layer().
		If we are, the current circle is considered to be a hotspot, and is added to the list.
		"""

		if self._inHotspotsLayer():
			try:
				name = attrs['inkscape:label']
			except KeyError:
				name = attrs['id']

			if name.startswith('hotspot.'):
				try:
					rect = self.svg_rects[name[8:]]
					rect.hotspot = (
						float(attrs['cx']),
						float(attrs['cy']))
				except KeyError:
					warn("Hotspot '{}' has not corresponding slice".format(name))
					pass

	def startElement(self, name, attrs):
		"""Generic hook for examining and/or parsing all SVG tags"""

		if options.debug:
			dbg("Beginning element '{}'".format(name))
		if name == 'svg':
			self.startElement_svg(name, attrs)
		elif name == 'title':
			self.startElement_title(name, attrs)
		elif name == 'g':
			# inkscape layers are groups, I guess, hence 'g'
			self._startElement_layer(name, attrs)
		elif name == 'rect':
			self._startElement_rect(name, attrs)
		elif name == 'circle':
			self._startElement_circle(name, attrs)

	def endElement(self, name):
		"""Generic hook called when the parser is leaving each SVG tag"""

		dbg("Ending element '{}'".format(name))
		if name == 'g':
			self._endElement_layer(name)
		elif name == 'title':
			self.endElement_title(name)

	def renderSVG(self, output, size):
		scale = size / svgLayerHandler.size
		# reset input filestream
		self.file.seek(0)
		
		p = subprocess.run(
			[
				rsvg_convert_path,
				'--zoom={}'.format(scale),
				'--format=png',
			], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=self.file)
		if p.returncode == 0:
			with open(output, 'wb') as f:
				f.write(p.stdout)
		else:
			dbg("rsvg-convert: {}".format(p.stderr.decode('utf8')))

def generateXCursor(pngs_directory, hotspots_directory):
	"""
	Generate X11 cursors from `*.in` files in `hotspots_directory` directory
	assumes path in input files are local to `pngs_directory`
	cursers will be created in the Theme directory
	"""

	for entry in os.scandir(hotspots_directory):
		if not entry.name.endswith('.in') or not entry.is_file():
			continue
		name = os.path.splitext(entry.name)[0]
		dbg("xcursorgen {hotspots}/{name}.in {odir}/cursors/{name}".format(
			odir=output_directory, hotspots=hotspots_directory, name=name))
		subprocess.run(
			[
				xcursorgen_path, '--prefix', pngs_directory,
				'{}/{}.in'.format(hotspots_directory, name),
				'{}/cursors/{}'.format(output_directory, name)
			], check = True)

if options.anicur:
	class Args:
		""" Fake the arguments so that we can include anicursorgen"""
		def __init__(self, prefix=os.getcwd()):
			self.prefix = prefix
		def __getattr__(self, attr):
			if attr == 'prefix':
				return self.prefix
			else:
				return None

	from anicursorgen import make_cursor_from

	def generateWindowsCursor(pngs_directory, hotspots_directory):
		for entry in os.scandir(hotspots_directory):
			args = Args(prefix=pngs_directory)
			if not entry.name.endswith('.in') or not entry.is_file():
				continue
			name = os.path.splitext(entry.name)[0]
			if is_animated_cursor(hotspots_directory, name):
				suffix = 'ani'
			else:
				suffix = 'cur'
			input_config = open(entry.path, 'r')
			output_file = open('{}/{}.{}'.format(output_directory, name, suffix), 'wb')
			make_cursor_from(input_config, output_file, args)
			input_config.close()

def is_animated_cursor(hotspots_directory, name):
	""" Check if configuration file belongs to an animated cursor """
	with open('{}/{}.in'.format(hotspots_directory, name), 'r') as f:
		for l in f.readlines():
			line = l.split()
			try:
				duration = int(line[4])
			except:
				continue
			if duration > 0:
				return True
		return False

def make_animated_cursor_apng(pngs_directory, size, name):
	try:
		p = subprocess.run([
			ffmpeg_path,
			'-i', '{src_dir}/{size}/{name}_%04d.png'.format(src_dir=pngs_directory, size=size, name=name),
			'-plays', '0', # loop indefinetly
			'-r', '{:.2f}'.format(fps),
			'-f', animated_preview_format['ffmpeg_format'],
			'-y', # always overwrite output file
			'{dest_dir}/{name}_{size}.{ext}'.format(
				dest_dir=pngs_directory, size=size, name=name, ext=animated_preview_format['suffix'])
		], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf8')

		if p.returncode != 0 or options.debug:	
			print(p.stdout)
	except FileNotFoundError:
		warn("ffmpeg not found. Cannot generate animated preview image")

class SVGFilter(saxutils.XMLFilterBase):
	def __init__(self, upstream, downstream, mode, **kwargs):
		saxutils.XMLFilterBase.__init__(self, upstream)
		self._downstream = downstream
		self.mode = mode

	def startDocument(self):
		self.in_throwaway_layer_stack = [False]

	def startElement(self, localname, attrs):
		def modify_style (style, old_style, new_style=None):
			styles = style.split (';')
			new_styles = []
			if old_style is not None:
				match_to = old_style + ':'
			for s in styles:
				if len (s) > 0 and (old_style is None or not s.startswith (match_to)):
					new_styles.append(s)
			if new_style is not None:
				new_styles.append(new_style)
			return ';'.join(new_styles)

		dict = {}
		is_throwaway_layer = False
		is_slices = False
		is_hotspots = False
		is_shadows = False
		is_layer = False
		if localname == 'g':
			for key, value in attrs.items():
				if key == 'inkscape:label':
					if value == 'slices':
						is_slices = True
					elif value == 'hotspots':
						is_hotspots = True
					elif value == 'shadow':
						is_shadows = True
				elif key == 'inkscape:groupmode':
					if value == 'layer':
						is_layer = True
		idict = {}
		idict.update(attrs)
		if 'style' not in attrs.keys():
			idict['style'] = ''
		for key, value in idict.items():
			alocalname = key
			if alocalname == 'style':
				had_style = True
			if alocalname == 'style' and is_slices:
				value = modify_style(value, 'display', 'display:none')
			if alocalname == 'style' and is_hotspots:
				if 'hotspots,' in self.mode:
					value = modify_style(value, 'display', 'display:inline')
				else:
					value = modify_style(value, 'display', 'display:none')
			if alocalname == 'style' and is_shadows:
				if 'shadows,' in self.mode:
					value = modify_style(value, 'filter', 'filter:url(#drop_shadow)')
				else:
					value = modify_style(value, 'filter', None)
			value = modify_style(value, 'shape-rendering', None)
			dict[key] = value

		if self.in_throwaway_layer_stack[0] or is_throwaway_layer:
			self.in_throwaway_layer_stack.insert(0, True)
		else:
			self.in_throwaway_layer_stack.insert(0, False)
			attrs = xmlreader.AttributesImpl(dict)
			self._downstream.startElement(localname, attrs)

	def characters(self, content):
		if self.in_throwaway_layer_stack[0]:
			return
		self._downstream.characters(content)

	def endElement(self, localname):
		if self.in_throwaway_layer_stack.pop(0):
			return
		self._downstream.endElement(localname)

if __name__ == '__main__':
	svgFilename = options.input_file[0]

	info("Parsing file {}".format(svgFilename))
	# Try to parse the svg file
	svgLayerHandler = SVGLayerHandler(svgFilename)

	# verify that the svg file actually contained some rectangles.
	if len(svgLayerHandler.svg_rects) == 0:
		fatalError("No slices were found in this SVG file. Please refer to the documentation for guidance on how to use this SVGSlice.  As a quick summary:\n" + usageMsg)
	else:
		dbg("Parsing successful.")

	# set paths from SVG metadata or cmdline
	output_directory = None
	if options.output_directory is not None:
		output_directory = options.output_directory
	if options.theme_name is not None:
		svgLayerHandler.title = options.theme_name

	if output_directory is None:
		if svgLayerHandler.title is not None:
			output_directory = svgLayerHandler.title
		else:
			fatalError("Neiter cursor output directory provided (--out), nor svg title set")
	
	if svgLayerHandler.title is None:
		fatalError("Neiter cursor theme name provided (--name), nor svg title set")

	# sanity warnings
	if not svgLayerHandler.slices_hidden:
		warn("'slices' layer is visible")
	if not svgLayerHandler.hotspots_hidden:
		warn("'hotspots' layer is visible")

	# manual cleanup
	if options.clean:
		info("Running cleanup.")
		shutil.rmtree(output_directory)
		shutil.rmtree(pngs_directory)
		shutil.rmtree(hotspots_directory)
		sys.exit(0)

	# setup output directories
	if options.force:
		try:
			shutil.rmtree(output_directory)
		except FileNotFoundError:
			pass

	if options.fps:
		fps = float(options.fps)
	if options.sizes:
		sizes = list(map(lambda x: int(x), options.sizes.split(',')))

	if os.path.isdir(output_directory):
		fatalError("Theme directory exists, run with -f or --force to overwrite")
	if options.anicur:
		os.makedirs('{}'.format(output_directory))
	else:
		os.makedirs('{}/cursors'.format(output_directory))

	for size in sizes:
		os.makedirs('{}/{}'.format(pngs_directory, size), exist_ok=True)
	os.makedirs(hotspots_directory, exist_ok=True)

	# render pngs of of cursors
	for size in sizes:
		info("Generating PNGs for size: {}".format(size))
		output = '{opath}/{size}.png'.format(size=size, opath=pngs_directory)
		svgLayerHandler.renderSVG(output, size)
		with PIL.Image.open(output, 'r') as img:
			# loop through each slice rectangle, crop the corresponding pngs
			for rect in svgLayerHandler.svg_rects.values():
					rect.cropFromTemplate(img, size, pngs_directory)

	info("Converting {} cursor files".format(len(svgLayerHandler.svg_rects)))
	# loop through each slice rectangle and write corresponding X11 cursors
	for rect in sorted(svgLayerHandler.svg_rects.values(), key=lambda x: x.name):
		rect.writeCursorConfig(pngs_directory, hotspots_directory)
	
	if options.anicur:
		generateWindowsCursor(pngs_directory, hotspots_directory)
	else:
		generateXCursor(pngs_directory, hotspots_directory)

	if not options.anicur:
		info("Writing metadata for theme '{}'".format(svgLayerHandler.title))
		# generate theme
		svgLayerHandler.linkCursorNames(icon_names_database, output_directory)
		svgLayerHandler.writeThemeDescription(output_directory)

	if options.test:
		# make an animation preview
		for rect in svgLayerHandler.svg_rects.values():
			(name, frame) = rect.get_animated_cursor_name()
			if frame == 1: # only generate for once per frameset
				info("Generating animated preview for: '{}'".format(name))
				for size in sizes:
					make_animated_cursor_apng(pngs_directory, size, name)
	else:
		info("Cleanup")
		shutil.rmtree(pngs_directory)
		shutil.rmtree(hotspots_directory)

	info("All Done.")
