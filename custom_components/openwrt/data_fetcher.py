"""
get openwrt info by token and sysauth
"""

import logging
import requests
import re
import asyncio
import json
import time
import datetime
from urllib import parse

from async_timeout import timeout
from aiohttp.client_exceptions import ClientConnectorError
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from .const import (
    DO_URL,
)

_LOGGER = logging.getLogger(__name__)



class DataFetcher:
    """fetch the openwrt data"""

    def __init__(self, hass, host, username, passwd):

        self._host = host
        self._username = username
        self._passwd = passwd
        self._hass = hass
        self._session_client = async_create_clientsession(hass)
        self._data = {}
    
    def requestget_data(self, url, headerstr):
        responsedata = requests.get(url, headers=headerstr)
        if responsedata.status_code != 200:
            return responsedata.status_code
        json_text = responsedata.content.decode('utf-8')
        resdata = json.loads(json_text)
        return resdata
        
    def requestpost_data(self, url, headerstr, datastr):
        responsedata = requests.post(url, headers=headerstr, data = datastr, verify=False)
        if responsedata.status_code != 200:
            return responsedata.status_code
        json_text = responsedata.content.decode('utf-8')
        resdata = json.loads(json_text)
        return resdata
        
    def requestget_data_text(self, url, headerstr, datastr):
        responsedata = requests.post(url, headers=headerstr, verify=False)
        if responsedata.status_code != 200:
            return responsedata.status_code
        resdata = responsedata.content.decode('utf-8')
        return resdata
        
    def requestpost_json(self, url, headerstr, json_body):
        responsedata = requests.post(url, headers=headerstr, json = json_body, verify=False)
        if responsedata.status_code != 200:
            return responsedata.status_code
        json_text = responsedata.content.decode('utf-8')
        resdata = json.loads(json_text)
        return resdata

    def requestpost_cookies(self, url, headerstr, body):
        responsedata = requests.post(url, headers=headerstr, data = body, verify=False, allow_redirects=False)
        if responsedata.status_code == 403:            
            return 403
        if responsedata.status_code != 200 and responsedata.status_code != 302:
            return responsedata.status_code        
        resdata = responsedata.cookies["sysauth"]
        return resdata         
        
    async def _login_openwrt(self):
        hass = self._hass
        host = self._host
        username =self._username
        passwd =self._passwd
        header = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

        body = "luci_username=" + username + "&luci_password=" + passwd
        url =  host + DO_URL
        
        try:
            async with timeout(10): 
                resdata = await self._hass.async_add_executor_job(self.requestpost_cookies, url, header, body) 
                if resdata ==403:
                    _LOGGER.debug("OPENWRT Username or Password is wrong，please reconfig!")
                    return resdata
                else:                   
                    _LOGGER.debug("login_successfully for OPENWRT")
        except (
            ClientConnectorError
        ) as error:
            raise UpdateFailed(error)
        _LOGGER.debug("Requests remaining: %s", url)          
       
        return resdata
        
    
    def seconds_to_dhms(self, seconds):
        days = seconds // (3600 * 24)
        hours = (seconds // 3600) % 24
        minutes = (seconds // 60) % 60
        seconds = seconds % 60
        if days > 0 :
            return ("{0}天{1}小时{2}分钟".format(days,hours,minutes))
        if hours > 0 :
            return ("{0}小时{1}分钟".format(hours,minutes))
        if minutes > 0 :
            return ("{0}分钟{1}秒".format(minutes,seconds))
        return ("{0}秒".format(seconds)) 
        

    async def _get_openwrt_status(self, sysauth):
        header = {
            "Cookie": "sysauth=" + sysauth
        }
        
        parameter = "?status=1"
        
        body = ""

        url =  self._host + DO_URL + parameter
        url2 = self._host + DO_URL + "/admin/status/overview"
        
        try:
            async with timeout(10): 
                resdata = await self._hass.async_add_executor_job(self.requestget_data, url, header)
                resdata2 = await self._hass.async_add_executor_job(self.requestget_data_text, url2, header, body)
        except (
            ClientConnectorError
        ) as error:
            raise UpdateFailed(error)
        _LOGGER.debug("Requests remaining: %s", url)
        _LOGGER.debug(resdata)
        if resdata == 401 or resdata == 403:
            self._data = 401
            return        
        
        # resdata["cpuinfo"] = " 1795.377 MHz    +20.0°C  (crit = +100.0°C) \n" 
        self._data = {}
        if resdata.get("cpuinfo"):
            cpuinfo = resdata["cpuinfo"]
        elif resdata.get("cpuwd"):
            cpuinfo = resdata["cpuwd"]
        else:
            cpuinfo = ""
        cputemp = re.findall(r"\+(.+?)°C",cpuinfo)
         
        #_LOGGER.debug(cputemp)
        if cputemp:
            if isinstance(cputemp,list):
                self._data["openwrt_cputemp"] = cputemp[0]
        else:
            self._data["openwrt_cputemp"] = 0
        self._data["openwrt_cpufre"] = cpuinfo.split( )[0]
        self._data["openwrt_userinfo"] = resdata["userinfo"].replace("\n%","")
        self._data["openwrt_conncount"] = resdata["conncount"] 
        self._data["openwrt_uptime"] = self.seconds_to_dhms(resdata["uptime"])        
        self._data["openwrt_cpu"] = resdata["cpuusage"].replace("\n%","")
        self._data["openwrt_memory"] = round((1 - resdata["memory"]["available"]/resdata["memory"]["total"])*100,0)
        self._data["openwrt_memory_attrs"] = resdata["memory"]
        if resdata.get("wan"):
            self._data["openwrt_wan_ip"] = resdata["wan"]["ipaddr"]
            self._data["openwrt_wan_ip_attrs"] = resdata["wan"]
            self._data["openwrt_wan_uptime"] = self.seconds_to_dhms(resdata["wan"]["uptime"]) 
        else:
            self._data["openwrt_wan_ip"] = ""
            self._data["openwrt_wan_uptime"] = ""
        if resdata.get("wan6"):
            self._data["openwrt_wan6_ip"] = resdata["wan6"]["ip6addr"]
            self._data["openwrt_wan6_ip_attrs"] = resdata["wan6"]
            self._data["openwrt_wan6_uptime"] = self.seconds_to_dhms(resdata["wan6"]["uptime"]) 
        else:
            self._data["openwrt_wan6_ip"] = ""
            self._data["openwrt_wan6_uptime"] = ""
        # self._data["openwrt_upload"] = round(resdata["Data"]["sysstat"]["stream"]["upload"]/1024/1024, 3)
        # self._data["openwrt_download"] = round(resdata["Data"]["sysstat"]["stream"]["download"]/1024/1024, 3)
        # self._data["openwrt_total_up"] = round(resdata["Data"]["sysstat"]["stream"]["total_up"]/1024/1024/1024, 2)
        # self._data["openwrt_total_down"] = round(resdata["Data"]["sysstat"]["stream"]["total_down"]/1024/1024/1024, 2)
        openwrtversion = resdata2.replace("\n","").replace("\r","")
        self._data["openwrt_kernel"] = re.findall(r"内核版本</td><td>(.+?)</td>", openwrtversion)[0]
        self._data["openwrt_name"] = re.findall(r"<meta name=\"application-name\" content=\"(.+?) - LuCI", openwrtversion)[0]
        self._data["openwrt_version"] = re.findall(r"固件版本</td><td>(.+?)</td>", openwrtversion)[0].replace("\t","")
        self._data["openwrt_cpu_brand"] = re.findall(r"型号</td><td>(.+?) :", openwrtversion)[0]
        
        
        querytime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._data["querytime"] = querytime

        return
  
    async def _get_openwrt_version(self, sysauth):
        header = {
            "Cookie": "sysauth=" + sysauth
        }
             
        body = ""
        url =  self._host + DO_URL + "/admin/status/overview"        
        try:
            async with timeout(10): 
                resdata = await self._hass.async_add_executor_job(self.requestget_data_text, url, header, body)
        except (
            ClientConnectorError
        ) as error:
            raise UpdateFailed(error)
        _LOGGER.debug("Requests remaining: %s", url)        
        if resdata == 401 or resdata == 403:
            self._data = 401
            return
        openwrtinfo = {}
        resdata = resdata.replace("\n","").replace("\r","")
        openwrtinfo["sw_version"] = re.findall(r"内核版本</td><td>(.+?)</td>", str(resdata))
        openwrtinfo["device_name"] = re.findall(r"<meta name=\"application-name\" content=\"(.+?) - LuCI", resdata)[0]
        openwrtinfo["model"] = re.findall(r"固件版本</td><td>(.+?)</td>", resdata)

        return openwrtinfo
        
        
    async def get_data(self, sysauth):  
        threads = [
            self._get_openwrt_status(sysauth),
        ]
        await asyncio.wait(threads)
                    
        return self._data


class GetDataError(Exception):
    """request error or response data is unexpected"""
