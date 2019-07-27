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

Please remember to HIDE the slices layer before exporting, so that the rectangles themselves are not drawn in the final image slices."""

# Inkscape provides dimensions for the slice boxes. All slices need to be of the same size.
# Inkscape is renders once each size and with PIL/Pillow's crop we cut the correct cursor
# Mark cursor hotspot with a dot (x,y position counts; not the center), and name it "id", with a 'hotspot.' prefix
# xcursorgen is provided with the scaled and cropped pngs for each cursor and the corresponding hotspot information
# names.txt (real name is the first in each line, link names come after that, spaces seperated) generates symlinks for the theme

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

# generated cursor sizes
sizes = [ 24, 32, 48, 64, 96 ]

fps = 16.66666

# synonym database for X11 cursor
icon_names_database = 'names.txt'

# directory for generated hotspots includes for xcursorgen
hotspots_directory = 'hotspots'
# directory for generated cursor pngs
pngs_directory = 'pngs'

# command used to call inkscape shell mode
inkscape_command = [ 'flatpak', 'run', 'org.inkscape.Inkscape', '--shell' ]
# executable for xcursorgen
xcursorgen_path = 'xcursorgen'
# executable for ffmpeg (used to generated animated previews in -t mode)
ffmpeg_path = 'ffmpeg'
# animated preview format (for ffmpeg) and file suffix
animated_preview_format = { 'ffmpeg_format': 'apng', 'suffix': 'apng'}

from xml.sax import saxutils, make_parser, SAXParseException, handler
from xml.sax.handler import feature_namespaces
import os, sys, stat, tempfile, shutil
import subprocess, fcntl, gzip
import PIL.Image

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

def set_nonblocking(file):
	""" Set fileobject to nonblocking mode """

	mask = fcntl.fcntl(file.fileno(), fcntl.F_GETFL) | os.O_NONBLOCK
	fcntl.fcntl(file.fileno(), fcntl.F_SETFL, mask)

def set_blocking(file):
	""" Set fileobject to blocking mode """

	mask = fcntl.fcntl(file.fileno(), fcntl.F_GETFL) & ~os.O_NONBLOCK
	fcntl.fcntl(file.fileno(), fcntl.F_SETFL, mask)

class Inkscape:
	""" Inkscape process handle """

	def __init__(self, svgLayerHandler):
		self.fd = svgLayerHandler.fd

		self._process = subprocess.Popen(
			inkscape_command,
			stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
			encoding='utf8', pass_fds=[ self.fd ])
		
		bb = self._getBoundingBoxes()

		svgLayerHandler.fixBoundingBoxes(bb)

	def _render(self, args):
		""" send commandline arguments to inkscape, svg file is appended """

		dbg('inkscape ' + args)

		# flush stdout buffer
		self._process.stdin.write('\n')
		self._process.stdin.flush()
		set_nonblocking(self._process.stdout)
		text = self._process.stdout.readline()
		while not text.startswith('>'):
			if len(text) > 0:
				dbg(text.rstrip())
			text = self._process.stdout.readline()
		
		self._process.stdin.write(args + ' /proc/self/fd/{}\n'.format(self.fd))
		self._process.stdin.flush()

		# flush stdout buffer
		text = self._process.stdout.readline()
		while not text.startswith('>'):
			if len(text) > 0:
				dbg(text.rstrip())
			text = self._process.stdout.readline()
		set_blocking(self._process.stdout)

		# check if inkscape is still running
		if self._process.returncode is not None:
			msg = self._process.communicate()
			dbg("inkscape failed with errorcode {}\n{}".format(self._process.returncode, msg[1]))
			raise RuntimeError("inkscape error")

	def _getBoundingBoxes(self):
		"""
		Load bounding boxes for all objects in the document.
		Positions and size are in user units (should be pixels)
		"""

		bounding_boxes = dict()

		# flush stdout buffer
		self._process.stdin.write('\n')
		self._process.stdin.flush()
		set_nonblocking(self._process.stdout)
		text = self._process.stdout.readline()
		while not text.startswith('>'):
			if len(text) > 0:
				dbg(text.rstrip())
			text = self._process.stdout.readline()
	
		self._process.stdin.write('--query-all /proc/self/fd/{}\n'.format(self.fd))
		self._process.stdin.flush()

		# read list from process stdout
		text = self._process.stdout.readline()
		while not text.startswith('>'):
			if len(text) > 0:
				dbg(text.rstrip())
				v = (text.rstrip().split(','))
				bounding_boxes[v[0]] = { 'x': float(v[1]), 'y': float(v[2]), 'w': float(v[3]), 'h': float(v[4]) }
			text = self._process.stdout.readline()
		set_blocking(self._process.stdout)
		
		# check if inkscape is still running
		if self._process.returncode is not None:
			msg = self._process.communicate()
			dbg("inkscape failed with errorcode {}\n{}".format(self._process.returncode, msg[1]))
			raise RuntimeError("inkscape error")
		return bounding_boxes

	def renderSVG(self, svgLayerHandler, size, output):
		"""
		render SVG to PNG output for provided target size.
		size is the target size for one slice, the whole document is scaled accordingly
		"""

		scale = size / svgLayerHandler.size
		w = round(svgLayerHandler.width * scale)
		h = round(svgLayerHandler.height * scale)
		self._render('-w {w} -h {h} --export-png="{output}"'.format(
			w=w, h=h, output=output, input=input))

	def close(self):
		msg = self._process.communicate('quit\n')
		os.close(self.fd)
		dbg(msg[0])
		dbg(msg[1])

	def __enter__(self):
		return self

	def __exit__(self, type, value, traceback):
		self.close()

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

		(sliceName, frame) = get_animated_cursor_name(self.name)

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
		# named slices bounding box will be added later by inkscape
		self.svg_rects = []
		self._layer_nests = 0
		self.slices_hidden = False
		self.hotspots_hidden = False
		# read by inkscape
		self.size = None
		self.file = self._openFile()
		# handle for inkscape
		self.fd = os.dup(self.file.fileno())
		self._runParser()

	def _openFile(self):
		# open svg and compressed svgz alike
		suffix = os.path.splitext(svgFilename)[1]
		if suffix == '.svg':
			return open(svgFilename, 'r')
		elif suffix in [ '.svgz', '.gz' ]:
			return gzip.open(svgFilename, 'r')
		else:
			fatalError("Unknown file extension: {}".format(suffix))

	def _runParser(self):
		xmlParser = make_parser()
		xmlParser.setFeature(feature_namespaces, 0)

		# setup XML Parser with an SVGLayerHandler class as a callback parser ####
		xmlParser.setContentHandler(self)

		try:
			xmlParser.parse(self.file)
		except SAXParseException as e:
			fatalError("Error parsing SVG file '{}': {},{}: {}.  If you're seeing this within inkscape, it probably indicates a bug that should be reported.".format(
				self.svgFilename, e.getLineNumber(), e.getColumnNumber(), e.getMessage()))

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

	def _add(self, rect):
		"""Adds the given rect to the list of rectangles successfully parsed"""

		self.svg_rects.append(rect)

	def _startElement_layer(self, name, attrs):
		"""
		Callback hook for parsing layer elements

		Checks to see if we're starting to parse a slices layer, and sets the appropriate flags.
		Otherwise, the layer will simply be ignored.
		"""

		dbg("found layer: name='{}'".format(name))
		if attrs.get('inkscape:groupmode', None) == 'layer':
			if self._inSlicesLayer() or attrs['inkscape:label'] == 'slices':
				self._layer_nests += 1

			if attrs['inkscape:label'] == 'slices':
				self.slices_hidden = self._isHidden(attrs)
			elif attrs['inkscape:label'] == 'hotspots':
				self.hotspots_hidden = self._isHidden(attrs)

	def _endElement_layer(self, name):
		"""
		Callback for leaving a layer in the SVG file

		Just undoes any flags set previously.
		"""

		dbg("leaving layer: name='{}'".format(name))
		if self._inSlicesLayer():
			self._layer_nests -= 1

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
			self._add(rect)

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
		elif name in 'rect':
			self._startElement_rect(name, attrs)

	def endElement(self, name):
		"""Generic hook called when the parser is leaving each SVG tag"""

		dbg("Ending element '{}'".format(name))
		if name == 'g':
			self._endElement_layer(name)
		elif name == 'title':
			self.endElement_title(name)
		elif name == 'svg':
			self.svg_rects.sort(key=lambda x: x.name)

	def fixBoundingBoxes(self, bb):
		""" Load bounding box information from inkscape output """

		for layer in self.svg_rects:
			sl = bb[layer.name]
			if round(sl['h']) != round(sl['w']):
				fatalError("SVG slice {} not square: {} != {}".format(layer.name, sl['w'], sl['h']))
			if self.size is None:
				self.size = round(sl['w'])
			elif self.size != round(sl['w']) or self.size != round(sl['h']):
				fatalError("SVG slice {} of inconsitent size: {} != {}".format(layer.name, self.size, sl['w']))
			layer.slice = (sl['x'], sl['y'], sl['w'], sl['h'])
			try:
				hs = bb['hotspot.' + layer.name]
				layer.hotspot = (hs['x'] - sl['x'] + hs['w']/2, hs['y'] - sl['y'] + hs['h']/2)
			except KeyError:
				warn("{} has no hotspot defined, defaulting to (0, 0)".format(layer.name))
				layer.hotspot(0,0)
			
			if layer.hotspot[0] < 0 or layer.hotspot[0] < 0 or layer.hotspot[0] > layer.slice[2] or layer.hotspot[1] > layer.slice[3]:
				warn("Hotspot for {name} is out of slice by ({x:.2f}, {y:.2f}), defaulting to (0,0)".format(
					name=layer.name, x=layer.hotspot[0], y=layer.hotspot[1]))
				layer.hotspot = (0,0)

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

def get_animated_cursor_name(name):
	sliceName = name
	frame = -1

	if sliceName[-5:].startswith('_'):
		try:
			frame = int(sliceName[-4:])
			sliceName = sliceName[:-5]
		except ValueError:
			pass
	return (sliceName, frame)

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

	if p.returncode != 0:	
		print(p.stdout)

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
	os.makedirs('{}/cursors'.format(output_directory))

	for size in sizes:
		os.makedirs('{}/{}'.format(pngs_directory, size), exist_ok=True)
	os.makedirs(hotspots_directory, exist_ok=True)

	# setup handle to inkscape shell
	with Inkscape(svgLayerHandler) as inkscape:
		# render pngs of of cursors
		for size in sizes:
			info("Generating PNGs for size: {}".format(size))
			output = '{opath}/{size}.png'.format(size=size, opath=pngs_directory)
			inkscape.renderSVG(svgLayerHandler, size, output)
			with PIL.Image.open(output, 'r') as img:
				# loop through each slice rectangle, crop the corresponding pngs
				for rect in svgLayerHandler.svg_rects:
						rect.cropFromTemplate(img, size, pngs_directory)

	info("Converting {} cursor files".format(len(svgLayerHandler.svg_rects)))
	# loop through each slice rectangle and write corresponding X11 cursors
	for rect in svgLayerHandler.svg_rects:
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
		for rect in svgLayerHandler.svg_rects:
			(name, frame) = get_animated_cursor_name(rect.name)
			if frame == 1: # only generate for once per frameset
				info("Generating animated preview for: '{}'".format(name))
				for size in sizes:
					make_animated_cursor_apng(pngs_directory, size, name)
	else:
		info("Cleanup")
		shutil.rmtree(pngs_directory)
		shutil.rmtree(hotspots_directory)

	info("All Done.")