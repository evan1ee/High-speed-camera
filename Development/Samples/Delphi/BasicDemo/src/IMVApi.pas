unit IMVApi;

interface

uses
  Windows, SysUtils, Variants, Classes, IMVDefines;


function  IMV_GetIntFeatureValue(Var handle:Pointer;const strKey:PAnsiChar;pIntValue:PInt64):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_GetDoubleFeatureValue(Var handle:Pointer;const strKey:PAnsiChar;pDoubleValue:PDouble):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_GetBoolFeatureValue(Var handle:Pointer;const strKey:PAnsiChar;pBoolValue:Pbool):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_GetEnumFeatureValue(Var handle:Pointer;const strKey:PAnsiChar;pEnumValue:PUint64):Integer; stdcall; external 'MVSDKmd.dll';


function  IMV_SetIntFeatureValue(Var handle:Pointer;const strKey:PAnsiChar;intValue:Int64):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_SetDoubleFeatureValue(Var handle:Pointer;const strKey:PAnsiChar;doubleValue:Double):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_SetBoolFeatureValue(Var handle:Pointer;const strKey:PAnsiChar;boolValue:bool):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_SetEnumFeatureValue(Var handle:Pointer;const strKey:PAnsiChar;enumValue:Uint64):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_GetStringFeatureValue(Var handle:Pointer;const strKey:PAnsiChar;pStringValue:PIMV_Stirng):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_SetStringFeatureValue(Var handle:Pointer;const strKey:PAnsiChar;pStringValue:PAnsiChar):Integer; stdcall; external 'MVSDKmd.dll';

function  IMV_ExecuteCommandFeature(Var handle:Pointer;const strKey:PAnsiChar):Integer; stdcall; external 'MVSDKmd.dll';


function  IMV_EnumDevices(Var pDeviceList:IMV_DeviceList;interfaceType:DWORD):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_CreateHandle(Var handle:PPointer;mode:IMV_ECreateHandleMode;Var pIdentifier:Pointer):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_Open(Var handle:Pointer):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_Close(Var handle:Pointer):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_DestroyHandle(Var handle:Pointer):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_StartGrabbing(Var handle:Pointer):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_StopGrabbing(Var handle:Pointer):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_GetFrame(Var handle:Pointer;pFrame:PIMV_FrameInfo;timeoutMS:Integer):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_ReleaseFrame(Var handle:Pointer;pFrame:PIMV_FrameInfo):Integer; stdcall; external 'MVSDKmd.dll';
function  IMV_PixelConvert(Var handle:Pointer;pstPixelConvertParam:PIMV_PixelConvertParam):Integer; stdcall; external 'MVSDKmd.dll';

function  VR_Open(pParam:PVR_OPEN_PARAM_S;Var pHandle:PPointer):Integer; stdcall; external 'VideoRender.dll';
function  VR_RenderFrame(Var handle:Pointer;param:PVR_FRAME_S;pEnlargeRect:PVR_RECT):Integer; stdcall; external 'VideoRender.dll';
function  VR_Close(Var handle:Pointer):Integer; stdcall; external 'VideoRender.dll';

function DeviceInfoToShow( pDeviceInfo:IMV_DeviceInfo; Var pInfoToShow:string): Integer;
function IsWin32:Boolean;
function Open(hwnd:HwND;width:Integer;height:Integer):Boolean;
function Display(displayBuffer:Pointer;iWidth:Integer;iHeight:Integer;iPixelFormat:VR_PIXEL_TYPE_E):Boolean;
function DisplayClose():Boolean;
function ConvertToBGR24(hDevHandle: PPointer;frame:PIMV_Frame;m_pBufForDriver:PPAnsiChar;m_nBufSizeForDriver:Cardinal;stPixelConvertParam:IMV_PixelConvertParam):Boolean;

function GetIntValue( hDevHandle: PPointer; const strKey: String; pnIntValue: Pint64): Integer;
function SetIntValue( hDevHandle: PPointer; const strKey: String; nIntValue: Int64): Integer;
function GetEnumValue( hDevHandle: PPointer; const strKey: String; pnEnumValue: PUInt64): Integer;
function SetEnumValue( hDevHandle: PPointer; const strKey: String; nEnumValue: UInt64): Integer;
function GetFloatValue( hDevHandle: PPointer; Const strKey: String; pfFloatValue: PDouble): Integer;
function SetFloatValue( hDevHandle: PPointer; const strKey: String; fFloatValue: Double): Integer;
function GetBoolValue( hDevHandle: PPointer; const strKey: String; pbBoolValue: PBool): Integer;
function SetBoolValue( hDevHandle: PPointer; const strKey: String; bBoolValue: Bool): Integer;
function GetStringValue( hDevHandle: PPointer; const strKey: String; Var pStrValue: string):Integer;
function SetStringValue( hDevHandle: PPointer; const strKey: String; pstrValue: String ):Integer;
function SetCommandValue( hDevHandle: PPointer; const strKey: String ):Integer;

// Support common operation


// Convert the C-Style char sequences to String
function _FormaCtName(const Format: string): string;  cdecl;
// allows us to use "varargs" in Delphi
const  FormatCName: function(const Format: string): string; cdecl varargs = _FormaCtName;


implementation

Var
   m_nRet : Integer;
  m_params:VR_OPEN_PARAM_S;
  m_handle:PPointer;
  renderParam:VR_FRAME_S;
  rect:VR_Rect;


// Parse and display the Gige device information
function DeviceInfoToShow( pDeviceInfo:IMV_DeviceInfo; Var pInfoToShow:string): Integer;
Var
  strUserName: PAnsiChar;
  IP:PAnsiChar;

begin
  if 0<>pDeviceInfo.cameraName[0] then
  begin
    strUserName := PAnsiChar(@pDeviceInfo.cameraName);
  end
  else
  begin
    strUserName := PAnsiChar(@pDeviceInfo.vendorName);
  end;
  if(pDeviceInfo.nCameraType=typeGigeCamera) then
  begin
    IP := PAnsiChar(@pDeviceInfo.SpecificDeviceInfo.gigeDeviceInfo.ipAddress);
    pInfoToShow := 'GigE: '+strUserName +'('+IP+')';
  end
  else
  begin
    pInfoToShow := 'USB: ' + strUserName;
  end;
  Result := IMV_OK;
end;



// Get Integer value
function GetIntValue( hDevHandle: PPointer; const strKey: String; pnIntValue: PInt64): Integer;
Var
  pAnsiKey: PAnsiChar;

begin
  if (Nil = hDevHandle) or (0 = length(strKey)) or (Nil = pnIntValue) then
  begin
    Result := IMV_INVALID_PARAM;
    exit
  end;

  pAnsiKey := PAnsiChar(AnsiString(strKey));
  Result := IMV_GetIntFeatureValue(hDevHandle^, pAnsiKey, pnIntValue);
end;

// Set Integer value
function SetIntValue( hDevHandle: PPointer; const strKey: String; nIntValue: Int64): Integer;
Var
  pAnsiKey: PAnsiChar;

begin
  if (Nil = hDevHandle) or (0 = length(strKey)) then
  begin
    Result := IMV_INVALID_PARAM;
    exit
  end;

  pAnsiKey := PAnsiChar(AnsiString(strKey));
  Result := IMV_SetIntFeatureValue(hDevHandle^, pAnsiKey, nIntValue);
end;


// Get Enum value
function GetEnumValue( hDevHandle: PPointer; const strKey: String; pnEnumValue: PUInt64): Integer;
Var
  pAnsiKey: PAnsiChar;

begin
  if (Nil = hDevHandle) or (0 = length(strKey)) or (Nil = pnEnumValue) then
  begin
    Result := IMV_INVALID_PARAM;
    exit
  end;

  pAnsiKey := PAnsiChar(AnsiString(strKey));
  Result := IMV_GetEnumFeatureValue(hDevHandle^, pAnsiKey, pnEnumValue);

end;


// Set Enum value
function SetEnumValue( hDevHandle: PPointer; const strKey: String; nEnumValue: UInt64): Integer;
Var
  pAnsiKey: PAnsiChar;

begin
  if (Nil = hDevHandle) or (0 = length(strKey)) then
  begin
    Result := IMV_INVALID_PARAM;
    exit
  end;

  pAnsiKey := PAnsiChar(AnsiString(strKey));
  Result := IMV_SetEnumFeatureValue(hDevHandle^, pAnsiKey, nEnumValue);
end;


// Get Float value
function GetFloatValue( hDevHandle: PPointer; const strKey: String; pfFloatValue: PDouble): Integer;
Var
  pAnsiKey: PAnsiChar;

begin
  if (Nil = hDevHandle) or (0 = length(strKey)) then
  begin
    Result := IMV_INVALID_PARAM;
    exit
  end;

  pAnsiKey := PAnsiChar(AnsiString(strKey));
  Result := IMV_GetDoubleFeatureValue(hDevHandle^, pAnsiKey, pfFloatValue);

end;


// Set Float value
function SetFloatValue( hDevHandle: PPointer; const strKey: String; fFloatValue: Double): Integer;
Var
  pAnsiKey: PAnsiChar;

begin
  if (Nil = hDevHandle) or (0 = length(strKey)) then
  begin
    Result := IMV_INVALID_PARAM;
    exit
  end;

  pAnsiKey := PAnsiChar(AnsiString(strKey));
  Result := IMV_SetDoubleFeatureValue(hDevHandle^, pAnsiKey, fFloatValue);
end;


// Get Boolean value
function GetBoolValue( hDevHandle: PPointer; const strKey: String; pbBoolValue: PBool): Integer;
Var
  pAnsiKey: PAnsiChar;
  nBoolNode: Bool;

begin
  if (Nil = hDevHandle) or (0 = length(strKey)) or (Nil = pbBoolValue) then
  begin
    Result := IMV_INVALID_PARAM;
    exit
  end;

  pAnsiKey := PAnsiChar(AnsiString(strKey));
  Result := IMV_GetBoolFeatureValue(hDevHandle^, pAnsiKey, @nBoolNode);

end;


// Set Boolean value
function SetBoolValue( hDevHandle: PPointer; const strKey: String; bBoolValue: Bool): Integer;
Var
  pAnsiKey: PAnsiChar;

begin
  if (Nil = hDevHandle) or (0 = length(strKey)) then
  begin
    Result := IMV_INVALID_PARAM;
    exit
  end;

  pAnsiKey := PAnsiChar(AnsiString(strKey));
  Result := IMV_SetBoolFeatureValue(hDevHandle^, pAnsiKey, bBoolValue);
end;


// Get String value
function GetStringValue( hDevHandle: PPointer; const strKey: String; Var pStrValue: string):Integer;
Var
  pAnsiKey: PAnsiChar;
  pStringValue:IMV_String;
  str:string;
begin
  if (Nil = hDevHandle) or (0 = length(strKey)) then
  begin
    Result := IMV_INVALID_PARAM;
    exit
  end;

  pAnsiKey := PAnsiChar(AnsiString(strKey));
  Result := IMV_GetStringFeatureValue(hDevHandle^, pAnsiKey, @pStringValue);
   SetString(str,PAnsiChar(@pStringValue.strGet[0]),sizeof(pStringValue.strGet));
   pStrValue:=str;

end;


// Set String value
function SetStringValue( hDevHandle: PPointer; const strKey: String; pstrValue: String ):Integer;
Var
  pAnsiKey: PAnsiChar;
  pAnsiValue: PAnsiChar;

begin
  if (Nil = hDevHandle) or (0 = length(strKey)) then
  begin
    Result := IMV_INVALID_PARAM;
    exit
  end;

  pAnsiKey := PAnsiChar(AnsiString(strKey));
  pAnsiValue := PAnsiChar(AnsiString(pstrValue));
  Result := IMV_SetStringFeatureValue(hDevHandle^, pAnsiKey, pAnsiValue);
end;


// Set Command value
function SetCommandValue( hDevHandle: PPointer; const strKey: String ):Integer;
Var
  pAnsiKey: PAnsiChar;

begin
  if (Nil = hDevHandle) or (0 = length(strKey)) then
  begin
    Result := IMV_INVALID_PARAM;
    exit
  end;

  pAnsiKey := PAnsiChar(AnsiString(strKey));
  Result := IMV_ExecuteCommandFeature(hDevHandle^, pAnsiKey);
end;


// Convert the C-Style char sequences to String
function _FormaCtName(const Format: string): string; cdecl;
const
  StackSlotSize = SizeOf(Pointer);
var
  Args: va_list;
  Buffer: array[0..63] of Char;
begin
  Args := va_list(PAnsiChar(@Format) + ((SizeOf(Format) + StackSlotSize - 1) and not (StackSlotSize - 1)));
  SetString(Result, Buffer, wvsprintf(Buffer, PChar(Format), Args));
end;


function IsWin32: Boolean;
var
  Kernel32Handle: THandle;
  IsWow64Process: function(Handle: Windows.THandle; var Res: Windows.BOOL): Windows.BOOL;
stdcall;
GetNativeSystemInfo :
  procedure(var lpSystemInfo: TSystemInfo); stdcall; isWoW64 :BOOL;SystemInfo :  TSystemInfo;
  const
    PROCESSOR_ARCHITECTURE_AMD64 = 9;
    PROCESSOR_ARCHITECTURE_IA64 = 6;
  begin
    Kernel32Handle := GetModuleHandle('KERNEL32.DLL');
    if Kernel32Handle = 0 then
      Kernel32Handle := LoadLibrary('KERNEL32.DLL');
    if Kernel32Handle <> 0 then
    begin
      IsWow64Process := GetProcAddress(Kernel32Handle, 'IsWow64Process');
      GetNativeSystemInfo := GetProcAddress(Kernel32Handle, 'GetNativeSystemInfo');
      if Assigned(IsWow64Process) then
      begin
        IsWow64Process(GetCurrentProcess, isWoW64);
        Result := isWoW64 and Assigned(GetNativeSystemInfo);
        if Result then
        begin
          GetNativeSystemInfo(SystemInfo);
          Result := (SystemInfo.wProcessorArchitecture = PROCESSOR_ARCHITECTURE_AMD64) or (SystemInfo.wProcessorArchitecture = PROCESSOR_ARCHITECTURE_IA64);
        end;
      end
      else
        Result := False;
    end
    else
      Result := False;
  end;


function Open(hwnd:HwND;width:Integer;height:Integer):Boolean;
begin
  ZeroMemory(@m_params,sizeof(VR_OPEN_PARAM_S));
  m_params.eVideoRenderMode:=VR_MODE_GDI;
  m_params.hWnd:=hwnd;
  m_params.nWidth:=width;
  m_params.nHeight:=height;
  VR_Open(@m_params,m_handle);
  result:=true;
end;

function Display(displayBuffer:Pointer;iWidth:Integer;iHeight:Integer;iPixelFormat:VR_PIXEL_TYPE_E):Boolean;
begin
   ZeroMemory(@renderParam,sizeof(VR_FRAME_S));
   renderParam.data[0]:=displayBuffer;
   renderParam.stride[0]:=iWidth;
   renderParam.nWidth:=iWidth;
   renderParam.nHeight:=iHeight;
   if(iPixelFormat=VR_PIXEL_FMT_RGB24)then
   begin
     renderParam.format:=VR_PIXEL_FMT_RGB24;
   end
   else if(iPixelFormat=VR_PIXEL_FMT_MONO8)then
   begin
     renderParam.format:=VR_PIXEL_FMT_MONO8;
   end;
   rect.right:=iWidth;
   rect.bottom:=iHeight;

   VR_RenderFrame(m_handle^,@renderParam,@rect);
   Result := True;
end;

function DisplayClose():Boolean;
begin
    VR_Close(m_handle^);
    Result := True;
end;

function ConvertToBGR24(hDevHandle: PPointer;frame:PIMV_Frame;m_pBufForDriver:PPAnsiChar;m_nBufSizeForDriver:Cardinal;stPixelConvertParam:IMV_PixelConvertParam):Boolean;
begin
   ZeroMemory(@stPixelConvertParam,sizeof(IMV_PixelConvertParam));
   if(Nil = m_pBufForDriver^) or (frame.frameInfo.size * 3>m_nBufSizeForDriver) then
   begin
     if(Nil<>m_pBufForDriver^) then
     begin
       StrDispose(m_pBufForDriver^);
     end;
     m_pBufForDriver^ := AnsiStrAlloc(frame.frameInfo.size*3);
     m_nBufSizeForDriver := frame.frameInfo.size*3;
      if (Nil=m_pBufForDriver^) or (not(StrBufSize(m_pBufForDriver^)>0)) then
     begin
       Result:=false;
       exit
     end;
   end;

    // convert image to BGR8
    stPixelConvertParam.nWidth:=frame.frameInfo.width;
    stPixelConvertParam.nHeight:=frame.frameInfo.height;
    stPixelConvertParam.ePixelFormat:=frame.frameInfo.pixelFormat;
    stPixelConvertParam.pSrcData:=frame.pData;
    stPixelConvertParam.nSrcDataLen:=frame.frameInfo.size;
    stPixelConvertParam.nPaddingX:=frame.frameInfo.paddingX;
    stPixelConvertParam.nPaddingY:=frame.frameInfo.paddingY;
    stPixelConvertParam.eBayerDemosaic:=demosaicBilinear;
    stPixelConvertParam.eDstPixelFormat:= gvspPixelBGR8;
    stPixelConvertParam.pDstBuf:= m_pBufForDriver^;
    stPixelConvertParam.nDstBufSize:=m_nBufSizeForDriver;

    m_nRet:=IMV_PixelConvert(hDevHandle^,@stPixelConvertParam);
    if(m_nRet<>IMV_OK)then
    begin
      Result:=false;
    end
    else
    begin
      Result:=true;
    end;
end;

end.
