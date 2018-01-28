"""
MIT License

Copyright (c) 2018 Jordan Maxwell
Written 1/28/2018

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import os, sys
from cefpython3 import cefpython
from panda3d.core import CardMaker, Texture, NodePath
from direct.directnotify.DirectNotify import DirectNotify

class PandaChromiumManager(object):
    """
    Manages global space code for CEFPython
    """
    notify = DirectNotify().newCategory('PandaChromiumManager')

    def __init__(self):
        self._loop_task = None

    def initialize(self, settings=None):
        """
        Initializes PandaChrome and CEFPython
        """

        # Retrieve logging level
        notify_level = config.GetString('notify-level', 'info')
        custom_level = config.GetString('cefpython-level', 'info')
        log_level = notify_level
        if custom_level != notify_level:
            log_level = custom_level
        
        cef_levels = {
            'info': cefpython.LOGSEVERITY_INFO,
            'warning': cefpython.LOGSEVERITY_WARNING,
            'error': cefpython.LOGSEVERITY_ERROR
        }

        if log_level not in cef_levels:
            self.notify.warning('%s is not a valid CEFPython log level; Defaulting to info' % log_level)
            log_level = 'info'
        log_level = cef_levels[log_level]

        # Attempt to build settings from prc
        prc_settings = {
            'log_severity': log_level,
            'release_dcheck_enabled': config.GetBool('cefpython-release-dcheck-enabled', False),
            'locales_dir_path': cefpython.GetModuleDirectory()+"/locales",
            'resources_dir_path': cefpython.GetModuleDirectory(),
            'browser_subprocess_path': '%s/%s' % (cefpython.GetModuleDirectory(), 'subprocess')    
        }
        
        # update with supplied settings if present
        if settings is not None:
            prc_settings.update(settings)

        cefpython.g_debug = config.GetBool('cefpython-gdebug', False)
        cefpython.Initialize(settings)

        #Initialize looping task
        taskMgr.add(self._perform_cef_loop, 'CefPythonMessageLoop')

    def _perform_cef_loop(self, task):
        cefpython.MessageLoopWork()
        return task.cont

    def shutdown(self):
        """
        Shuts down PandaChrome and CEFPython. 
        Should be called on application shutdown.
        """
        # Remove the task
        if self._loop_task:
            taskMgr.remove(self._loop_task)

        # Stop CEFPython
        cefpython.Shutdown()

class CEFClientException(Exception):
    """
    Base class for all CEFClientHandler exceptions
    """

class CEFClientHandler(object):
    """
    A custom client handler for CEFPython that processes callbacks from the browser to Panda
    """

    def __init__(self, browser, texture):
        self._browser = browser
        self._texture = texture

    @property
    def browser(self):
        return self._browser

    @property
    def texture(self):
        return self._texture

    def OnPaint(self, browser, element_type, dirty_rects, paint_buffer, width, height):
        img = self.texture.modify_ram_image()
        if element_type == cefpython.PET_VIEW:
            img.set_data(paint_buffer.GetString(mode="rgba", origin="bottom-left"))
        else:
            raise CEFClientException("Unknown elemenet_type: %s" % element_type)

    def GetViewRect(self, browser, rect_out):
        width  = self.texture.getXSize()
        height = self.texture.getYSize()
        rect_out.extend([0, 0, width, height])
        return True

    def GetScreenPoint(self, browser, viewX, viewY, screenCoordinates):
        return False

    def OnLoadEnd(self, browser, frame, http_code):
        return

    def OnLoadError(self, browser, frame, errorCode, errorText, failedURL):
        raise CEFClientException('Failed to load; %s %s %s %s %s'
            % (browser, frame, errorCode, errorText, failedURL))

class ChromiumTexture(Texture):
    """
    Custom texture object for applying PandaChromium browser to the scene graph
    """
    notify = DirectNotify().newCategory('ChromiumTexture')

    def __init__(self, name=None, window_handle=None, browser_settings=None, navigation_url=None):
        
        if name is None:
            name = self.__class__.__name__
        self._browser = None
        
        # Setup Texture
        Texture.__init__(self, name)

        size_width = config.GetInt('pchromium-texture-width', 1024)
        size_height = config.GetInt('pchromium-texture-height', 1024)
        self.set_x_size(size_width)
        self.set_y_size(size_height)
        self.set_compression(Texture.CMOff)
        self.set_component_type(Texture.TUnsignedByte)
        self.set_format(Texture.FRgba4)

        # No window info was provided. Grab the window handler from showbase
        if window_handle is None:
            window_handle = base.win.getWindowHandle().getIntHandle()
        window_info = cefpython.WindowInfo()
        window_info.SetAsOffscreen(window_handle)

        # Initialize browser
        self._browser = cefpython.CreateBrowserSync(window_info, browser_settings, navigateUrl=navigation_url)
        self._handler = CEFClientHandler(self._browser, self)
        self._browser.SendFocusEvent(True)
        self._browser.SetClientHandler(self._handler)
        self._browser.WasResized()

    @property
    def browser(self):
        return self._browser

    @property
    def handler(self):
        return self._handler

    def set_x_size(self, width):
        """
        Custom X Size handler that also resizes the browser
        """
        Texture.set_x_size(self, width)
        if self._browser:
            self._browser.WasResized()

    def set_y_size(self, height):
        """
        Custom Y Size handler that also resizes the browser
        """
        Texture.set_y_size(self, height)
        if self._browser:
            self._browser.WasResized()

class ChromiumNode(NodePath):
    """
    Custom Panda3D Node that contains a card for displaying a browser
    """

    def __init__(self, name=None, naivgation_url=None, browser_settings=None):

        if name is None:
            name = self.__class__.__name__
        NodePath.__init__(self, name)
        self._chrome_texture = ChromiumTexture('%s-ChromiumBrowserTexture' % name, navigation_url=naivgation_url, browser_settings=browser_settings)

        card_maker = CardMaker('chromebrowser2d')
        card_maker.set_frame(-0.75, 0.75, -0.75, 0.75)
        self._card = self.attach_new_node(card_maker.generate())
        self._card.set_texture(self._chrome_texture)

    def chrome_texture(self):
        return self._chrome_texture

    def card(self):
        return self._card