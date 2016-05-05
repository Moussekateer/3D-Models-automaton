import mouse, Image, os, subprocess, math, imgpie, threading, time, win32gui, win32con
import HLMVModel, Stitch, uploadFile, scriptconstants
from SendKeys import SendKeys
from screenshot import screenshot
from threadpool import threadpool
from win32api import GetKeyState
try:
	import psyco
	psyco.full()
except:
	pass

paintDict = scriptconstants.paintDict
BLUPaintDict = scriptconstants.BLUPaintDict
paintHexDict = scriptconstants.paintHexDict

degreesToRadiansFactor = math.pi / 180.0
outputImagesDir = r'output' # The directory where the output images will be saved.
SDKLauncherStartingPoint = (20, 20) # Rough x, y screen coordindates of SDK Launcher. This is near the top left of the screen by default.
monitorResolution = [1920, 1080] # The monitor resolution of the user in the form of a list; [pixel width, pixel height].
imgCropBoundaries = (1, 42, 1919, 799) # The cropping boundaries, as a pixel distance from the top left corner, for the images as a tuple; (left boundary, top boundary, right boundary, bottom boundary).
fileButtonCoordindates = (14, 32) # The coordinates for the File menu button in HLMV
threadedBlending = True # Use threading for blending computations
sleepFactor = 1.0 # Sleep time factor that affects how long the script waits for HLMV to load/models to load etc

def openHLMV(pathToHlmv):
	subprocess.Popen([pathToHlmv + os.sep + 'hlmv.exe'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def closeHLMV():
	subprocess.Popen(['taskkill', '/f', '/t' ,'/im', 'hlmv.exe'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def prepareHLMV():
	window_list = []
	def enum_callback(hwnd, results):
		window_list.append((hwnd, win32gui.GetWindowText(hwnd)))

	win32gui.EnumWindows(enum_callback, [])

	handle_id = None
	for hwnd, title in window_list:
		if 'half-life model viewer' in title.lower():
			handle_id = hwnd
			break
	win32gui.SetForegroundWindow(handle_id)
	win32gui.ShowWindow(handle_id, win32con.SW_MAXIMIZE)

def sleep(sleeptime):
	time.sleep(sleeptime*sleepFactor)

def paintHat(colour, VMTFile):
	vmt = open(VMTFile, 'rb').read()
	pattern = '"\$color2"\s+"\{(.[^\}]+)\}"'
	regex = re.compile(pattern, re.IGNORECASE)
	if regex.search(vmt):
		if colour == 'Stock':
			pattern2 = '(\s*)"\$colortint_base"\s+"\{(.[^\}]+)\}"'
			regex = re.compile(pattern2, re.IGNORECASE)
			result = regex.search(vmt)
			vmt = re.sub(pattern, '"$color2" "{' + result.group(2) + '}"', vmt)
		else:
			vmt = re.sub(pattern, '"$color2" "{' + colour + '}"', vmt)
	else:
		pattern = '(\s*)"\$colortint_base"\s+"\{(.[^\}]+)\}"'
		regex = re.compile(pattern, re.IGNORECASE)
		result = regex.search(vmt)
		if colour == 'Stock':
			vmt = re.sub(pattern, result.group(1) + '"$colortint_base" "{' + result.group(2) + '}"\n' + result.group(1).replace('\r\n','') + '"$color2" "{' + result.group(2) + '}"', vmt)
		else:
			vmt = re.sub(pattern, result.group(1) + '"$colortint_base" "{' + result.group(2) + '}"\n' + result.group(1).replace('\r\n','') + '"$color2" "{' + colour + '}"', vmt)
	f = open(VMTFile, 'wb')
	f.write(vmt)
	f.close()

def getBrightness(p):
	return (299.0 * p[0] + 587.0 * p[1] + 114.0 * p[2]) / 1000.0

def toAlphaBlackWhite(blackImg, whiteImg):
	size = blackImg.size
	blackImg = blackImg.convert('RGBA')
	loadedBlack = blackImg.load()
	loadedWhite = whiteImg.load()
	for x in range(size[0]):
		for y in range(size[1]):
			blackPixel = loadedBlack[x, y]
			whitePixel = loadedWhite[x, y]
			loadedBlack[x, y] = (
				(blackPixel[0] + whitePixel[0]) / 2,
				(blackPixel[1] + whitePixel[1]) / 2,
				(blackPixel[2] + whitePixel[2]) / 2,
				int(255.0 - 255.0 * (getBrightness(whitePixel) - getBrightness(blackPixel)))
			)
	return blackImg

def rotateAboutNewCentre(x, y, z, rotOffset, yAngle, xAngle):
	""" Method to position a model in HLMV with a new center of rotation.
	
		Parameters:
                x -> The current x position of the model.
				y -> The current y position of the model.
				z -> The current z position of the model.
				rotOffset -> The distance from the default centre of rotation to the new one (in HLMV units).
				yAngle -> The angle the model has been rotated by around the y axis, in degrees.
				xAngle -> The angle the model has been rotated by around the x axis, in degrees.
	"""
	if yAngle < 0:
		yAngle += 360 # HLMV goes -180 to 180, not 0 to 360.
	yAngle *= degreesToRadiansFactor
	xAngle *= degreesToRadiansFactor

	x += math.cos(yAngle) * rotOffset
	y += math.sin(yAngle) * rotOffset
	z -= math.sin(xAngle) * rotOffset
	return [x, y, z]

def offsetVertically(x, y, z, vertOffset, yAngle, xAngle):
	""" Method to position a model in HLMV with a new vertical offset
	
		Parameters:
                x -> The current x position of the model.
				y -> The current y position of the model.
				z -> The current z position of the model.
				vertOffset -> 
				yAngle -> The angle the model has been rotated by around the y axis, in degrees.
				xAngle -> The angle the model has been rotated by around the x axis, in degrees.
	"""
	if yAngle < 0:
		yAngle += 360 # HLMV goes -180 to 180, not 0 to 360.
	yAngle *= degreesToRadiansFactor
	xAngle *= degreesToRadiansFactor

	x += math.sin(xAngle) * (math.sin(yAngle) * vertOffset
	y += math.sin(xAngle) * (math.sin(yAngle) * vertOffset
	return [x, y, z]

class BlendingThread(threading.Thread):
	def __init__(self, xrotation, n, blackImages, whiteImages, saveDir, painted, teamColours):
		self.xrotation = xrotation
		self.n = n
		self.blackImages = blackImages
		self.whiteImages = whiteImages
		self.saveDir = saveDir
		self.painted = painted
		self.teamColours = teamColours
		self.started = False
	def join(self):
		if self.started:
			threading.Thread.join(self)
	def go(self, threaded=True):
		if threaded:
			self.started = True
			self.start()
		else:
			self.run()
	def start(self):
		threading.Thread.__init__(self)
		threading.Thread.start(self)
	def run(self):
		if self.painted:
			for colour in self.whiteImages:
				print 'Processing ' + colour
				if self.xrotation == -15:
					imgname = str(self.n) + '_1_' + paintHexDict[colour] + '.png'
				elif self.xrotation == 15:
					imgname = str(self.n) + '_-1_' + paintHexDict[colour] + '.png'
				else:
					imgname = str(self.n) + '_0_' + paintHexDict[colour] + '.png'
				black = imgpie.wrap(self.blackImages[colour])
				white = imgpie.wrap(self.whiteImages[colour])
				blended = black.blackWhiteBlend(white)
				blended.save(self.saveDir + os.sep + imgname)
		else:
			if self.teamColours:
				img = toAlphaBlackWhite(self.blackImages['RED'], self.whiteImages['RED'])
				img2 = toAlphaBlackWhite(self.blackImages['BLU'], self.whiteImages['BLU'])
				if self.xrotation == -15:
					imgname = str(self.n) + '_1_RED.png'
					imgname2 = str(self.n) + '_1_BLU.png'
				elif self.xrotation == 15:
					imgname = str(self.n) + '_-1_RED.png'
					imgname2 = str(self.n) + '_-1_BLU.png'
				else:
					imgname = str(self.n) + '_0_RED.png'
					imgname2 = str(self.n) + '_0_BLU.png'
				img.save(self.saveDir + os.sep + imgname, "PNG")
				img2.save(self.saveDir + os.sep + imgname2, "PNG")
			else:
				img = toAlphaBlackWhite(self.blackImages, self.whiteImages)
				if self.xrotation == -15:
					imgname = str(self.n) + '_1.png'
				elif self.xrotation == 15:
					imgname = str(self.n) + '_-1.png'
				else:
					imgname = str(self.n) + '_0.png'
				img.save(self.saveDir + os.sep + imgname, "PNG")

blendThread = None
def blendingMachine(*args, **kwargs):
	"""
	Dis is blending masheen.
	Poot things it, they get passed to BlendingThread.
	Whether they actually run threaded or not is up to the "threadedBlending" variable up there.
	It handles the join'ing of old threads, if it runs threaded in the first place.
	Make sure to call blendingMachine() without arguments when the thing is done, to ensure that threads (if any) terminate.
	"""
	global blendThread, threadedBlending
	if blendThread is not None:
		blendThread.join()
	if len(args) or len(kwargs):
		blendThread = BlendingThread(*args, **kwargs)
		blendThread.go(threaded=threadedBlending)

def automateDis(model,
				numberOfImages=24,
				n=0,
				rotationOffset=None,
				initialRotation=None,
				initialTranslation=None,
				verticalOffset=None,
				verticalRotations=1,
				screenshotPause=False,
				paint=False,
				teamColours=False,
				pathToHlmv='',
				itemName='',
				REDVMTFiles=None,
				BLUVMTFiles=None,
				wikiUsername=None,
				wikiPassword=None):
	""" Method to automize process of taking images for 3D model views. 
	
		Parameters:
                model -> An instance of a HLMVModelRegistryKey object for the model. Required.
				numberOfImages -> Number of images to take for one full rotation. Optional, default is 24.
				n -> Which nth step of rotation to start at. Optional, default is 0.
				rotationOffset -> The distance from the default centre of rotation to the new one (in HLMV units). Optional, default is none.
				initialRotation -> The initial model rotation as a tuple. Optional, default is (0 0 0).
				initialTranslation -> The initial model translation as a tuple. Optional, default is (0 0 0).
				verticalOffset -> The vertical offset for models that are centered in both other planes but not vertically. Optional, default is none.
				verticalRotations -> Int number where 1 = up/down rotations and 0 = no vertical rotations. Default is 1.
				screenshotPause -> Pause on every screenshot to pose model. Press number lock key to move on once finished posing. Default is False.
				paint -> Boolean to indicate whether model is paintable. Optional, default is False.
				teamColours -> Boolean to indicate whether model is team coloured. Optional, default is False.
				pathToHlmv -> Path to hlmv.exe. Usually in common\Team Fortress 2\bin
				itemName -> The name of the item. Optional, default is blank.
				REDVMTFiles -> The RED vmt file locations. Optional, default is none.
				BLUVMTFiles -> The BLU vmt file locations. Optional, default is none.
				wikiUsername -> wiki.tf2.com username. Optional, default is none.
				wikiPassword -> wiki.tf2.com password. Optional, default is none.
	"""

	folder = raw_input('Folder name for created images: ')
	outputFolder = outputImagesDir + os.sep + folder
	try:
		os.makedirs(outputFolder)
	except:
		answer = raw_input('Folder already exists, overwrite files? y\\n? ')
		if answer.lower() in ['no', 'n']:
			sys.exit(1)

	if initialTranslation is None:
		initialTranslation = [model.returnTranslation()['x'], model.returnTranslation()['y'], model.returnTranslation()['z']]
	if initialRotation is None:
		initialRotation = [model.returnRotation()['x'], model.returnRotation()['y'], model.returnRotation()['z']]

	# Time for user to cancel script start
	time.sleep(3)

	try:
		closeHLMV()
		sleep(2.0)
	except:
		pass
	print 'initialTranslation =', initialTranslation
	print 'initialRotation =', initialRotation
	
	model.setTranslation(x = initialTranslation[0], y = initialTranslation[1], z = initialTranslation[2])
	model.setNormalMapping(True)
	model.setBGColour(255, 255, 255, 255)
	for yrotation in range((-180 + (360/numberOfImages * n)), 180, 360/numberOfImages):
		print 'n =', str(n)
		for xrotation in range(-15, 30, 15):
			if (verticalRotations == 0 and xrotation == 0) or verticalRotations == 1:
				# Set rotation
				sleep(0.5)
				model.setRotation(x = xrotation + float(initialRotation[0]), y = yrotation + float(initialRotation[1]), z = initialRotation[2])
				print 'xRot = {0}, yRot = {1}'.format(xrotation, yrotation)
				if rotationOffset is not None:
					# Set translation to account for off centre rotation
					result = rotateAboutNewCentre(initialTranslation[0], initialTranslation[1], initialTranslation[2], rotationOffset, yrotation, xrotation)
					print 'translation =', result
					model.setTranslation(x = result[0], y = result[1], z = result[2])
					# Set translation to account for off centre horizontal rotation
				elif verticalOffset is not None:
					result = offsetVertically(initialTranslation[0], initialTranslation[1], initialTranslation[2], verticalOffset, yrotation, xrotation)
					print 'translation =', result
					model.setTranslation(x = result[0], y = result[1], z = result[2])
				# Open HLMV
				openHLMV(pathToHlmv)
				sleep(2)
				# Focus and maximise HLMV
				prepareHLMV()
				# Open recent model
				mouse.click(x=fileButtonCoordindates[0],y=fileButtonCoordindates[1])
				SendKeys(r'{DOWN 10}{RIGHT}{ENTER}')
				sleep(1)
				# If user wants to pose model before taking screenshot, make script wait
				if screenshotPause:
					numKeyState = GetKeyState(win32con.VK_NUMLOCK)
					while GetKeyState(win32con.VK_NUMLOCK) == numKeyState:
						pass
				# Item painting method
				def paintcycle(dict, whiteBackgroundImages, blackBackgroundImages):
					# Take whiteBG screenshots and crop
					for colour in dict:
						paintHat(dict[colour], REDVMTFiles)
						SendKeys(r'{F5}')
						sleep(1.0)
						imgWhiteBG = screenshot()
						imgWhiteBG = imgWhiteBG.crop(imgCropBoundaries)
						whiteBackgroundImages[colour] = imgWhiteBG
					# Change BG colour to black
					SendKeys(r'^b')
					# Take blackBG screenshots and crop
					for colour in dict:
						paintHat(dict[colour], REDVMTFiles)
						SendKeys(r'{F5}')
						sleep(1.0)
						imgBlackBG = screenshot()
						imgBlackBG = imgBlackBG.crop(imgCropBoundaries)
						blackBackgroundImages[colour] = imgBlackBG
					SendKeys(r'^b')
					SendKeys(r'{F5}')
					return whiteBackgroundImages, blackBackgroundImages
				if paint:
					whiteBackgroundImages = {}
					blackBackgroundImages = {}
					whiteBackgroundImages, blackBackgroundImages = paintcycle(paintDict, whiteBackgroundImages, blackBackgroundImages)
					if teamColours:
						# Change RED hat to BLU
						redFiles = []
						bluFiles = []
						for fileName in REDVMTFiles:
							redFiles.append(open(fileName, 'rb').read())
						for fileName in BLUVMTFiles:
							bluFiles.append(open(fileName, 'rb').read())
						for file, fileName in zip(bluFiles, redFileNames):
							with open(fileName, 'wb') as f:
								f.write(file)
						whiteBackgroundImages, blackBackgroundImages = paintcycle(BLUPaintDict, whiteBackgroundImages, blackBackgroundImages)
						for file, fileName in zip(bluFiles, redFileNames):
							with open(fileName, 'wb') as f:
								f.write(file)
					else:
						whiteBackgroundImages, blackBackgroundImages = paintcycle(BLUPaintDict, whiteBackgroundImages, blackBackgroundImages)
				else:
					if teamColours:
						# Take whiteBG screenshot and crop
						imgWhiteBGRED = screenshot()
						imgWhiteBGRED = imgWhiteBGRED.crop(imgCropBoundaries)
						# Change BG colour to black
						SendKeys(r'^b')
						# Take blackBG screenshot and crop
						imgBlackBGRED = screenshot()
						imgBlackBGRED = imgBlackBGRED.crop(imgCropBoundaries)
						# Change BG colour to white
						SendKeys(r'^b')
						# Change weapon colour to BLU
						redFiles = []
						bluFiles = []
						for fileName in REDVMTFiles:
							redFiles.append(open(fileName, 'rb').read())
						for fileName in BLUVMTFiles:
							bluFiles.append(open(fileName, 'rb').read())
						for file, fileName in zip(bluFiles, redFileNames):
							with open(fileName, 'wb') as f:
								f.write(file)
						SendKeys(r'{F5}')
						sleep(1.0)
						# Take whiteBG screenshot and crop
						imgWhiteBGBLU = screenshot()
						imgWhiteBGBLU = imgWhiteBGBLU.crop(imgCropBoundaries)
						# Change BG colour to black
						SendKeys(r'^b')
						# Take blackBG screenshot and crop
						imgBlackBGBLU = screenshot()
						imgBlackBGBLU = imgBlackBGBLU.crop(imgCropBoundaries)
						# Return VMT back to RED
						for file, fileName in zip(bluFiles, redFileNames):
							with open(fileName, 'wb') as f:
								f.write(file)
					else:
						# Take whiteBG screenshot and crop
						imgWhiteBG = screenshot()
						imgWhiteBG = imgWhiteBG.crop(imgCropBoundaries)
						# Change BG colour to black
						SendKeys(r'^b')
						# Take blackBG screenshot and crop
						imgBlackBG = screenshot()
						imgBlackBG = imgBlackBG.crop(imgCropBoundaries)
				# Remove background from images
				if paint:
					blendingMachine(xrotation, n, blackBackgroundImages, whiteBackgroundImages, outputFolder, True, True)
				else:
					if teamColours:
						blendingMachine(xrotation, n, {'RED':imgBlackBGRED,'BLU':imgBlackBGBLU}, {'RED':imgWhiteBGRED,'BLU':imgWhiteBGBLU}, outputFolder, False, True)
					else:
						blendingMachine(xrotation, n, imgBlackBG, imgWhiteBG, outputFolder, False, False)
				# Close HLMV
				closeHLMV()
				# Check for kill switch
				killKeyState = GetKeyState(win32con.VK_CAPITAL)
				if killKeyState in [1, -127]:
					print 'Successfully terminated'
					sys.exit(0)
		n += 1
	blendingMachine() # Wait for threads to finish, if any
	# Stitch images together
	print 'Stitching images together...'
	stitchPool = threadpool(numThreads=2, defaultTarget=Stitch.stitch)
	if paint:
		for colour in paintHexDict:
			if colour == 'Stock':
				if teamColours:
					finalImageName = itemName + ' RED 3D.jpg'
				else:
					finalImageName = itemName + ' 3D.jpg'
			elif colour == 'Stock (BLU)':
				if teamColours:
					finalImageName = itemName + ' BLU 3D.jpg'
			else:
				finalImageName = '{0} {1} 3D.jpg'.format(itemName, paintHexDict[colour])
			##### Need to thread this #####
			if colour != 'Stock (BLU)' or teamColours:
				stitchPool(outputFolder, paintHexDict[colour], finalImageName, numberOfImages, verticalRotations)
	else:
		if teamColours:
			finalREDImageName = itemName + ' RED 3D.jpg'
			finalBLUImageName = itemName + ' BLU 3D.jpg'
			stitchPool(outputFolder, 'RED', finalREDImageName, numberOfImages, verticalRotations)
			stitchPool(outputFolder, 'BLU', finalBLUImageName, numberOfImages, verticalRotations)
		else:
			finalImageName = itemName + ' 3D.jpg'
			stitchPool(outputFolder, None, finalImageName, numberOfImages, verticalRotations)
	stitchPool.shutdown()
	# Upload images to wiki
	if paint:
		for colour in paintHexDict:
			if colour == 'Stock':
				if teamColours:
					fileName = itemName + ' RED 3D.jpg'
				else:
					fileName = itemName + ' 3D.jpg'
			elif colour == 'Stock (BLU)':
				if teamColours:
					fileName = itemName + ' BLU 3D.jpg'
			else:
				fileName = '{0} {1} 3D.jpg'.format(itemName, paintHexDict[colour])
			url = uploadFile.fileURL(fileName)
			description = open(outputFolder + os.sep + fileName + ' offsetmap.txt', 'rb').read()
			description = description.replace('url = <nowiki></nowiki>', 'url = <nowiki>' + url + '</nowiki>')
			if colour != 'Stock (BLU)' or teamColours:
				uploadFile.uploadFile(outputFolder + os.sep + fileName, fileName, description, wikiUsername, wikiPassword, category='', overwrite=False)
	else:
		if teamColours:
			finalREDImageName = itemName + ' RED 3D.jpg'
			finalBLUImageName = itemName + ' BLU 3D.jpg'
			url = uploadFile.fileURL(finalREDImageName)
			url2 = uploadFile.fileURL(finalBLUImageName)
			description = open(outputFolder + os.sep + finalREDImageName + ' offsetmap.txt', 'rb').read()
			description = description.replace('url = <nowiki></nowiki>','url = <nowiki>' + url + '</nowiki>')
			description2 = open(outputFolder + os.sep + finalBLUImageName + ' offsetmap.txt', 'rb').read()
			description2 = description2.replace('url = <nowiki></nowiki>','url = <nowiki>' + url2 + '</nowiki>')
			uploadFile.uploadFile(outputFolder + os.sep + finalREDImageName, finalREDImageName, description, wikiUsername, wikiPassword, category='', overwrite=False)
			uploadFile.uploadFile(outputFolder + os.sep + finalBLUImageName, finalBLUImageName, description2, wikiUsername, wikiPassword, category='', overwrite=False)
		else:
			finalImageName = itemName + ' 3D.jpg'
			url = uploadFile.fileURL(finalImageName)
			description = open(outputFolder + os.sep + finalImageName + ' offsetmap.txt', 'rb').read()
			description = description.replace('url = <nowiki></nowiki>','url = <nowiki>' + url + '</nowiki>')
			uploadFile.uploadFile(outputFolder + os.sep + finalImageName, finalImageName, description, wikiUsername, wikiPassword, category='', overwrite=False)
	# All done yay
	print '\nAll done'

if __name__ == '__main__':
	# Poot values here
	starttime = time.time()
	
	# Example usage
	model = HLMVModel.HLMVModelRegistryKey('models.player.items.heavy.heavy_stocking_cap.mdl')
	automateDis(model = model,
				numberOfImages = 24,
				n = 0,
				rotationOffset = None,
				verticalOffset = None,
				verticalRotations = 1,
				screenshotPause = False,
				initialRotation = (0.000000, 0.000000, 0.000000),
				initialTranslation = (40.320000, 0.000000, 0.000000),
				paint = True,
				teamColours = True,
				pathToHlmv = r'F:\Steam\steamapps\common\Team Fortress 2\bin',
				itemName = 'User Moussekateer Test',
				REDVMTFiles = [r'E:\Steam\steamapps\moussekateer\team fortress 2\tf\materials\models\player\items\heavy\heavy_stocking_cap.vmt'],
				BLUVMTFiles = [r'E:\Steam\steamapps\moussekateer\team fortress 2\tf\materials\models\player\items\heavy\heavy_stocking_cap_blue.vmt'],
				wikiPassword = 'lolno'
				wikiUsername = 'Moussekateer',
				)

	print 'completed in ' + str(int(time.time() - starttime)) + 'seconds'
