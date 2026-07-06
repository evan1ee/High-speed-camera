unit IMVDefines;

interface

uses
  Windows, SysUtils, Variants, Classes;


const
   IMV_GVSP_PIX_MONO：Integer =$01000000;
   IMV_GVSP_PIX_RGB：Integer =$02000000;
   IMV_GVSP_PIX_COLOR：Integer =$02000000;
   IMV_GVSP_PIX_CUSTOM：Integer =$80000000;
   IMV_GVSP_PIX_COLOR_MASK：Integer =$FF000000;

   IMV_GVSP_PIX_OCCUPY1BIT: Integer = $00010000;
   IMV_GVSP_PIX_OCCUPY2BIT: Integer = $00020000;
   IMV_GVSP_PIX_OCCUPY4BIT: Integer = $00040000;
   IMV_GVSP_PIX_OCCUPY8BIT: Integer = $00080000;
   IMV_GVSP_PIX_OCCUPY12BIT: Integer = $000C0000;
   IMV_GVSP_PIX_OCCUPY16BIT: Integer = $00100000;
   IMV_GVSP_PIX_OCCUPY24BIT: Integer = $00180000;
   IMV_GVSP_PIX_OCCUPY32BIT: Integer = $00200000;
   IMV_GVSP_PIX_OCCUPY36BIT: Integer = $00240000;
   IMV_GVSP_PIX_OCCUPY48BIT: Integer = $00300000;


//function MV_PIXEL_BIT_COUNT( n: Integer ): Integer;
type IMV_EPixelType =
(
    // Undefined pixel type
    gvspPixelTypeUndefined = -1,

    // Mono Format
    gvspPixelMono1p = ($01000000 or $00010000 or $0037),
    gvspPixelMono2p =  ($01000000 or $00020000 or $0038),
    gvspPixelMono4p = ($01000000 or $00040000 or $0039),
    gvspPixelMono8 =  ($01000000 or $00080000 or $0001),
    gvspPixelMono8S = ($01000000 or $00080000 or $0002),
    gvspPixelMono10 =  ($01000000 or $00100000 or $0003),
    gvspPixelMono10Packed = ($01000000 or $000C0000 or $0004),
    gvspPixelMono12 =  ($01000000 or $00100000 or $0005),
    gvspPixelMono12Packed = ($01000000 or $000C0000 or $0006),
    gvspPixelMono14 =  ($01000000 or $00100000 or $0025),
    gvspPixelMono16 = ($01000000 or $00100000 or $0007),

    // Bayer Format
    gvspPixelBayGR8 =  ($01000000 or $00080000 or $0008),
    gvspPixelBayRG8 = ($01000000 or $00080000 or $0009),
    gvspPixelBayGB8 =  ($01000000 or $00080000 or $000A),
    gvspPixelBayBG8 = ($01000000 or $00080000 or $000B),
    gvspPixelBayGR10 =  ($01000000 or $00100000 or $000C),
    gvspPixelBayRG10 = ($01000000 or $00100000 or $000D),
    gvspPixelBayGB10 =  ($01000000 or $00100000 or $000E),
    gvspPixelBayBG10 = ($01000000 or $00100000 or $000F),
    gvspPixelBayGR12 =  ($01000000 or $00100000 or $0010),
    gvspPixelBayRG12 = ($01000000 or $00100000 or $0011),
    gvspPixelBayGB12 =  ($01000000 or $00100000 or $0012),
    gvspPixelBayBG12 = ($01000000 or $00100000 or $0013),
    gvspPixelBayGR10Packed =  ($01000000 or $000C0000 or $0026),
    gvspPixelBayRG10Packed = ($01000000 or $000C0000 or $0027),
    gvspPixelBayGB10Packed =  ($01000000 or $000C0000 or $0028),
    gvspPixelBayBG10Packed = ($01000000 or $000C0000 or $0029),
    gvspPixelBayGR12Packed =  ($01000000 or $000C0000 or $002A),
    gvspPixelBayRG12Packed =  ($01000000 or $000C0000 or $002B),
    gvspPixelBayGB12Packed = ($01000000 or $000C0000 or $002C),
    gvspPixelBayBG12Packed =  ($01000000 or $000C0000 or $002D),
    gvspPixelBayGR16 = ($01000000 or $00100000 or $002E),
    gvspPixelBayRG16 =  ($01000000 or $00100000 or $002F),
    gvspPixelBayGB16 = ($01000000 or $00100000 or $0030),
    gvspPixelBayBG16 =  ($01000000 or $00100000 or $0031),

    // RGB Format
    gvspPixelRGB8 =  ($02000000 or $00180000 or $0014),
    gvspPixelBGR8 = ($02000000 or $00180000 or $0015),
    gvspPixelRGBA8 =  ($02000000 or $00200000 or $0016),
    gvspPixelBGRA8 = ($02000000 or $00200000 or $0017),
    gvspPixelRGB10 =  ($02000000 or $00300000 or $0018),
    gvspPixelBGR10 = ($02000000 or $00300000 or $0019),
    gvspPixelRGB12 =  ($02000000 or $00300000 or $001A),
    gvspPixelBGR12 = ($02000000 or $00300000 or $001B),
    gvspPixelRGB16 =  ($02000000 or $00300000 or $0033),
    gvspPixelRGB10V1Packed = ($02000000 or $00200000 or $001C),
    gvspPixelRGB10P32 =  ($02000000 or $00200000 or $001D),
    gvspPixelRGB12V1Packed =  ($02000000 or $00240000 or $0034),
    gvspPixelRGB565P = ($02000000 or $00100000 or $0035),
    gvspPixelBGR565P =  ($02000000 or $00100000 or $0036),

    // YVR Format
    gvspPixelYUV411_8_UYYVYY = ($02000000 or $000C0000 or $001E),
    gvspPixelYUV422_8_UYVY =  ($02000000 or $00100000 or $001F),
    gvspPixelYUV422_8 = ($02000000 or $00100000 or $0032),
    gvspPixelYUV8_UYV =  ($02000000 or $00180000 or $0020),
    gvspPixelYCbCr8CbYCr = ($02000000 or $00180000 or $003A),
    gvspPixelYCbCr422_8 =  ($02000000 or $00100000 or $003B),
    gvspPixelYCbCr422_8_CbYCrY = ($02000000 or $00100000 or $0043),
    gvspPixelYCbCr411_8_CbYYCrYY =  ($02000000 or $000C0000 or $003C),
    gvspPixelYCbCr601_8_CbYCr = ($02000000 or $00180000 or $003D),
    gvspPixelYCbCr601_422_8 =  ($02000000 or $00100000 or $003E),
    gvspPixelYCbCr601_422_8_CbYCrY = ($02000000 or $00100000 or $0044),
    gvspPixelYCbCr601_411_8_CbYYCrYY =  ($02000000 or $000C0000 or $003F),
    gvspPixelYCbCr709_8_CbYCr = ($02000000 or $00180000 or $0040),
    gvspPixelYCbCr709_422_8 =  ($02000000 or $00100000 or $0041),
    gvspPixelYCbCr709_422_8_CbYCrY = ($02000000 or $00100000 or $0045),
    gvspPixelYCbCr709_411_8_CbYYCrYY =  ($02000000 or $000C0000 or $0042),

    // RGB Planar
    gvspPixelRGB8Planar =  ($02000000 or $00180000 or $0021),
    gvspPixelRGB10Planar = ($02000000 or $00300000 or $0022),
    gvspPixelRGB12Planar =  ($02000000 or $00300000 or $0023),
    gvspPixelRGB16Planar = ($02000000 or $00300000 or $0024),


    gvspPixelBayRG10p =  $010A0058,
    gvspPixelBayRG12p = $010c0059,
    gvspPixelMono1c =  $012000FF,
    gvspPixelMono1e = $01080FFF
);


const
  // Definition of correct code
  IMV_OK: Integer = 0;

  // ch:通用错误码定义 | en: Definition of common error code
  IMV_ERROR: Integer = -101;                          ///< \~chinese 成功，无错误							                  \~english Successed, no error
  IMV_INVALID_HANDLE: Integer = -102;                 ///< \~chinese 通用的错误							                    \~english Generic error
  IMV_INVALID_PARAM: Integer = -103;                  ///< \~chinese 错误或无效的句柄						                \~english Error or invalid handle
  IMV_INVALID_FRAME_HANDLE: Integer = -104;           ///< \~chinese 错误的参数							                    \~english Incorrect parameter
  IMV_INVALID_FRAME: Integer = -105;                  ///< \~chinese 错误或无效的帧句柄					                \~english Error or invalid frame handle
  IMV_INVALID_RESOURCE: Integer = -106;               ///< \~chinese 无效的帧								                    \~english Invalid frame
  IMV_INVALID_IP: Integer = -107;                     ///< \~chinese 相机/事件/流等资源无效			              	\~english Camera/Event/Stream and so on resource invalid
  IMV_NO_MEMORY: Integer = -108;                      ///< \~chinese 设备与主机的IP网段不匹配				            \~english Device's and PC's subnet is mismatch
  IMV_INSUFFICIENT_MEMORY: Integer = -109;            ///< \~chinese 内存不足								                    \~english Malloc memery failed
  IMV_ERROR_PROPERTY_TYPE: Integer = -110;            ///< \~chinese 传入的内存空间不足					                \~english Insufficient memory
  IMV_INVALID_ACCESS: Integer = -111;                 ///< \~chinese 属性类型错误							                  \~english Property type error
  IMV_INVALID_RANGE: Integer = -112;                  ///< \~chinese 属性不可访问、或不能读/写、或读/写失败	    \~english Property not accessible, or not be read/written, or read/written failed
  IMV_NOT_SUPPORT: Integer = -113;                    ///< \~chinese 属性值超出范围、或者不是步长整数倍	        \~english The property's value is out of range, or is not integer multiple of the step
                                                      ///< \~chinese 设备不支持的功能					                	\~english Device not supported function
  type
  PIMV_Stirng = ^IMV_String;
  IMV_String = record
    strGet:array[0..255] of Byte;
  end;
// device information
type
  IMV_GigEDeviceInfo = record
    nIpConfigOptions: Cardinal;                     /// Supported IP configuration options of device
    nIpConfigCurrent: Cardinal;                     /// Current IP Configuration options of device
    nReserved: array[0..2] of Cardinal;             ///< \~chinese 保留					\~english Reserved field

    macAddress: array[0..255] of Byte;              ///< \~chinese 设备Mac地址			\~english Device MAC Address
    ipAddress: array[0..255] of Byte;               ///< \~chinese 设备Ip地址			\~english Device ip Address
    subnetMask: array[0..255] of Byte;              ///< \~chinese 子网掩码				\~english SubnetMask
    defaultGateWay: array[0..255] of Byte;          ///< \~chinese 默认网关				\~english Default GateWay
    protocolVersion: array[0..255] of Byte;         ///< \~chinese 网络协议版本			\~english Net protocol version
    ipConfiguration: array[0..255] of Byte;         /// IP configuration valid
    chReserved: array[0..5,0..255] of Byte;         ///< \~chinese 保留					\~english Reserved field
end;

type
  IMV_UsbDeviceInfo = record
    bLowSpeedSupported: Boolean;                    ///< \~chinese true支持，false不支持，其他值 非法。	\~english true support,false not supported,other invalid
    bFullSpeedSupported: Boolean;                   ///< \~chinese true支持，false不支持，其他值 非法。	\~english true support,false not supported,other invalid
    bHighSpeedSupported: Boolean;                   ///< \~chinese true支持，false不支持，其他值 非法。	\~english true support,false not supported,other invalid
    bSuperSpeedSupported: Boolean;                  ///< \~chinese true支持，false不支持，其他值 非法。	\~english true support,false not supported,other invalid
    bDriverInstalled: Boolean;                      ///< \~chinese true安装，false未安装，其他值 非法。	\~english true support,false not supported,other invalid
    boolReserved:array[0..2] of Boolean;            ///< \~chinese 保留
    Reserved:array[0..3] of Cardinal;               ///< \~chinese 保留									\~english Reserved field

    configurationValid:array[0..255] of Byte;       ///< \~chinese 配置有效性							 \~english Configuration Valid
    genCPVersion:array[0..255] of Byte;             ///< \~chinese GenCP 版本							 \~english GenCP Version
    u3vVersion:array[0..255] of Byte;               ///< \~chinese U3V 版本号						   \~english U3v Version
    deviceGUID:array[0..255] of Byte;               ///< \~chinese 设备引导号							 \~english Device guid number
    familyName:array[0..255] of Byte;               ///< \~chinese 设备系列号							 \~english Device serial number
    u3vSerialNumber:array[0..255] of Byte;          ///< \~chinese 设备序列号							 \~english Device SerialNumber
    speed:array[0..255] of Byte;                    ///< \~chinese 设备传输速度						 \~english Device transmission speed
    maxPower:array[0..255] of Byte;                 ///< \~chinese 设备最大供电量					 \~english Maximum power supply of device
    chReserved:array[0..3,0..255] of Byte;          ///< \~chinese 保留									   \~english Reserved field

end;

type
   IMV_GigEInterfaceInfo = record
    description:array[0..255] of Byte;               ///< \~chinese  网卡描述信息		       \~english Network card description
    macAddress:array[0..255] of Byte;                ///< \~chinese  网卡Mac地址			     \~english Network card MAC Address
    ipAddress:array[0..255] of Byte;                 ///< \~chinese  设备Ip地址			       \~english Device ip Address
    subnetMask:array[0..255] of Byte;                ///< \~chinese  子网掩码			         \~english SubnetMask
    defaultGateWay:array[0..255] of Byte;            ///< \~chinese  默认网关			         \~english Default GateWay
    chReserved:array[0..4,0..255] of Byte;           ///< 保留						               	 \~english Reserved field
end;

type
   IMV_UsbInterfaceInfo = record
    description:array[0..255] of Byte;                ///< \~chinese  USB接口描述信息		   \~english USB interface description
    vendorID:array[0..255] of Byte;                   ///< \~chinese  USB接口Vendor ID	   \~english USB interface Vendor ID
    deviceID:array[0..255] of Byte;                   ///< \~chinese  USB接口设备ID		     \~english USB interface Device ID
    subsystemID:array[0..255] of Byte;                ///< \~chinese  USB接口Subsystem ID	 \~english USB interface Subsystem ID
    revision:array[0..255] of Byte;                   ///< \~chinese  USB接口Revision		   \~english USB interface Revision
    speed:array[0..255] of Byte;                      ///< \~chinese  USB接口speed		     \~english USB interface speed
    chReserved:array[0..3,0..255] of Byte;            ///< 保留						            	   \~english Reserved field
end;

type  IMV_ECameraType = (
       typeGigeCamera = 0,                            ///< \~chinese GIGE相机				\~english GigE Vision Camera
       typeU3vCamera = 1,                             ///< \~chinese USB3.0相机			\~english USB3.0 Vision Camera
       typeCLCamera = 2,                              ///< \~chinese CAMERALINK 相机		\~english Cameralink camera
       typePCIeCamera = 3,                            ///< \~chinese PCIe相机				\~english PCIe Camera
       typeUndefinedCamera = 255);                    ///< \~chinese 未知类型				\~english Undefined Camera


type
      IMV_EInterfaceType = LongWord;
const
      interfaceTypeGige: IMV_EInterfaceType = $00000001;           ///< \~chinese 网卡接口类型  		    \~english NIC type
      interfaceTypeUsb3: IMV_EInterfaceType = $00000002;           ///< \~chinese USB3.0接口类型		    \~english USB3.0 interface type
      interfaceTypeCL: IMV_EInterfaceType = $00000004;             ///< \~chinese CAMERALINK接口类型	  \~english Cameralink interface ty
      interfaceTypePCIe: IMV_EInterfaceType = $00000008;           ///< \~chinese PCIe接口类型          \~english PCIe interface type
      interfaceTypeAll: IMV_EInterfaceType = $00000000;            ///< \~chinese 忽略接口类型			    \~english All types interface type
      interfaceInvalidType: IMV_EInterfaceType = $FFFFFFFF;        ///< \~chinese 无效接口类型			    \~english Invalid interface type

type   IMV_ECreateHandleMode = (
        modeByIndex = 0,                             ///< \~chinese 通过已枚举设备的索引(从0开始，比如 0, 1, 2...)	  \~english By index of enumerated devices (Start from 0, such as 0, 1, 2...)
        modeByCameraKey,                             ///< \~chinese 通过设备键"厂商:序列号"							              \~english By device's key "vendor:serial number"
        modeByDeviceUserID,                          ///< \~chinese 通过设备自定义名								                 	\~english By device userID
        modeByIPAddress   );                         ///< \~chinese 通过设备IP地址									                  \~english By device IP address.

type   IMV_EBayerDemosaic = (
        demosaicNearestNeighbor,					           ///< \~chinese 最近邻			\~english Nearest neighbor
        demosaicBilinear,							               ///< \~chinese 双线性			\~english Bilinear
        demosaicEdgeSensing,						             ///< \~chinese 边缘检测		\~english Edge sensing
        demosaicNotSupport = 255);					         ///< \~chinese 不支持			\~english Not support


type
  DeviceSpecificInfo = record
    case integer of
    0: (gigeDeviceInfo: IMV_GigEDeviceInfo);          ///< \~chinese  Gige设备信息	\~english Gige Device Information
    1: (usbDeviceInfo: IMV_UsbDeviceInfo);            ///< \~chinese  Usb设备信息		\~english Usb  Device Information
 end;

 type
   InterfaceInfo = record
     case integer of
     0: (gigeInterfaceInfo:IMV_GigEInterfaceInfo);   ///< \~chinese  GigE网卡信息	\~english Gige interface Information
     1: (usbInterfaceInfo:IMV_UsbInterfaceInfo);     ///< \~chinese  Usb接口信息		\~english Usb interface Information
   end;

type
   PInnerStruct =^IMV_DeviceInfo;

     IMV_DeviceInfo =record
     nCameraType:IMV_ECameraType;                      ///< \~chinese 设备类别			\~english Camera type
     nCameraReserved:array[0..4] of Integer;           ///< \~chinese 保留				\~english Reserved field
     cameraKey:array[0..255] of Byte;                  ///< \~chinese 厂商:序列号		\~english Camera key
     cameraName:array[0..255] of Byte;                 ///< \~chinese 用户自定义名		\~english UserDefinedName
     serialNumber:array[0..255] of Byte;               ///< \~chinese 设备序列号		\~english Device SerialNumber
     vendorName:array[0..255] of Byte;                 ///< \~chinese 厂商				\~english Camera Vendor
     modelName:array[0..255] of Byte;                  ///< \~chinese 设备型号			\~english Device model
     manufactureInfo:array[0..255] of Byte;            ///< \~chinese 设备制造信息		\~english Device ManufactureInfo
     deviceVersion:array[0..255] of Byte;              ///< \~chinese 设备版本			\~english Device Version
     cameraReserved:array[0..4,0..255] of Byte;        ///< \~chinese 保留				\~english Reserved field
     SpecificDeviceInfo:DeviceSpecificInfo;
     nInterfaceType:IMV_EInterfaceType;                ///< \~chinese 接口类别			\~english Interface type
     nInterfaceReserved:array[0..4] of Integer;        ///< \~chinese 保留				\~english Reserved field
     interfaceName:array[0..255] of Byte;              ///< \~chinese 接口名			\~english Interface Name
     interfaceReserved:array[0..4,0..255] of Byte;     ///< \~chinese 保留				\~english Reserved field
     SpecificInterfaceInfo:InterfaceInfo;
 end;
   PIMV_DeviceList = ^IMV_DeviceList;
    IMV_DeviceList = record
    nDevNum:Cardinal;
    pDevInfo:PInnerStruct;
 end;




type
  PIMV_FrameInfo = ^IMV_FrameInfo;
  IMV_FrameInfo = record
  blockId: UInt64;                                ///< \~chinese 帧Id(仅对GigE/Usb/PCIe相机有效)					              \~english The block ID(GigE/Usb/PCIe camera only)
  status:Cardinal;                                ///< \~chinese 数据帧状态(0是正常状态)							                  \~english The status of frame(0 is normal status)
  width:Cardinal;                                 ///< \~chinese 图像宽度										                  	        \~english The width of image
  height:Cardinal;                                ///< \~chinese 图像高度											                          \~english The height of image
  size:Cardinal;                                  ///< \~chinese 图像大小										                  	        \~english The size of image
  pixelFormat:IMV_EPixelType;                     ///< \~chinese 图像像素格式									                 	        \~english The pixel format of image
  timeStamp:UInt64;                               ///< \~chinese 图像时间戳(仅对GigE/Usb/PCIe相机有效)			            \~english The timestamp of image(GigE/Usb/PCIe camera only)
  chunkCount:Cardinal;                            ///< \~chinese 帧数据中包含的Chunk个数(仅对GigE/Usb相机有效)	        \~english The number of chunk in frame data(GigE/Usb Camera Only)
  paddingX:Cardinal;                              ///< \~chinese 图像paddingX(仅对GigE/Usb/PCIe相机有效)			          \~english The paddingX of image(GigE/Usb/PCIe camera only)
  paddingY:Cardinal;                              ///< \~chinese 图像paddingY(仅对GigE/Usb/PCIe相机有效)		          	\~english The paddingY of image(GigE/Usb/PCIe camera only)
  recvFrameTime:Cardinal;                         ///< \~chinese 图像在网络传输所用的时间(单位:微秒,非GigE相机该值为0)	\~english The time taken for the image to be transmitted over the network(unit:us, The value is 0 for non-GigE camera)
  nReserved:array[0..18] of Cardinal;             ///< \~chinese 预留字段										                           	\~english Reserved field
  end;

type
 PIMV_Frame = ^IMV_Frame;
 IMV_Frame = record
   frameHandle:Pointer;                          ///< \~chinese 帧图像句柄(SDK内部帧管理用)					\~english Frame image handle(used for managing frame within the SDK)
   pData:PAnsiChar;                              ///< \~chinese 帧图像数据的内存首地址							\~english The starting address of memory of image data
   frameInfo:IMV_FrameInfo;                      ///< \~chinese 帧信息											        \~english Frame information
     nReserved:array[0..9] of Cardinal;          ///< \~chinese 预留字段											      \~english Reserved field
 end;

 type
  PIMV_PixelConvertParam = ^IMV_PixelConvertParam;
  IMV_PixelConvertParam = record
    nWidth:Cardinal;                             ///< [IN]	\~chinese 图像宽						            \~english Width
    nHeight:Cardinal;                            ///< [IN]	\~chinese 图像高					            	\~english Height
    ePixelFormat:IMV_EPixelType;                 ///< [IN]	\~chinese 像素格式						          \~english Pixel format
    pSrcData:PAnsiChar;                          ///< [IN]	\~chinese 输入图像数据					        \~english Input image data
    nSrcDataLen: Cardinal;                       ///< [IN]	\~chinese 输入图像长度					        \~english Input image length
    nPaddingX:Cardinal;                          ///< [IN]	\~chinese 图像宽填充					          \~english Padding X
    nPaddingY:Cardinal;                          ///< [IN]	\~chinese 图像高填充					          \~english Padding Y
    eBayerDemosaic:IMV_EBayerDemosaic;           ///< [IN]	\~chinese 转换Bayer格式算法				      \~english Alorithm used for Bayer demosaic
    eDstPixelFormat:IMV_EPixelType;              ///< [IN]	\~chinese 目标像素格式					        \~english Destination pixel format
    pDstBuf:PAnsiChar;                           ///< [OUT]	\~chinese 输出数据缓存(调用者分配缓存)	\~english Output data buffer(allocated cache by the caller)
    nDstBufSize:Cardinal;                        ///< [IN]   \~chinese 提供的输出缓冲区大小  		    \~english Provided output buffer size
    nDstDataLen:Cardinal;                        ///< [OUT]	\~chinese 输出数据长度          		    \~english Output data length
    nReserved:array[0..7] of Cardinal;           ///<		\~chinese 预留							                \~english Reserved field
  end;

type   IMV_CAM_TRIGGER_MODE = (
       IMV_TRIGGER_MODE_OFF = 0,            // ch:关闭 | en:Off
       IMV_TRIGGER_MODE_ON = 1);            // ch:打开 | en:ON

type   IMV_CAM_TRIGGER_SOURCE = (
       IMV_TRIGGER_SOURCE_SOFTWARE = 0,
       IMV_TRIGGER_SOURCE_LINE1 = 1,
       IMV_TRIGGER_SOURCE_LINE2 = 2
       );

// ch:自动曝光模式 | en:Auto Exposure Mode
type  IMV_CAM_EXPOSURE_AUTO_MODE = (
       IMV_EXPOSURE_AUTO_MODE_OFF = 0,            // ch:关闭 | en:Off
       IMV_EXPOSURE_AUTO_MODE_ONCE = 1,            // ch:一次 | en:Once
       IMV_EXPOSURE_AUTO_MODE_CONTINUOUS = 2);            // ch:连续 | en:Continuous

// ch:采集模式 | en:Acquisition mode
type  IMV_CAM_ACQUISITION_MODE = (
       IMV_ACQ_MODE_SINGLE = 0,            // ch:单帧模式 | en:Single Mode
       IMV_ACQ_MODE_MUTLI = 1,            // ch:多帧模式 | en:Multi Mode
       IMV_ACQ_MODE_CONTINUOUS = 1);            // ch:持续采集模式 | en:Continuous Mode

// ch:增益模式 | en:Gain Mode
type  IMV_CAM_GAIN_MODE = (
       IMV_GAIN_MODE_OFF = 0,            // ch:关闭 | en:Single Mode
       IMV_GAIN_MODE_ONCE = 1,            // ch:一次 | en:Multi Mode
       IMV_GAIN_MODE_CONTINUOUS = 1);            // ch:连续 | en:Continuous Mode

type   VR_MODE_E = (
        VR_MODE_D3D = 0,            //使用D3D的方式进行显示
        VR_MODE_GDI,                //使用GDI显示模式
        VR_MODE_OPENGLX,            //使用Opengl的方式进行显示
        VR_MODE_X11);               //使用X11的方式进行显示

type   VR_PIXEL_TYPE_E = (
        VR_PIXEL_FMT_NONE = -1,
        VR_PIXEL_FMT_YUV420P,
        VR_PIXEL_FMT_RGB24,
        VR_PIXEL_FMT_MONO8);



type
   PVR_OPEN_PARAM_S = ^VR_OPEN_PARAM_S;
   VR_OPEN_PARAM_S = record
   hWnd:HwND;
   eVideoRenderMode:VR_MODE_E;
   nWidth:Integer;
   nHeight:Integer;
end;

type
   PVR_FRAME_S = ^VR_FRAME_S;
   VR_FRAME_S = record
     data: array[0..3] of PAnsiChar;
     stride:array[0..3] of Integer;
     nWidth:Integer;
     nHeight:Integer;
     format:VR_PIXEL_TYPE_E;
   end;

type
    PVR_Rect = ^VR_Rect;
    VR_Rect = record
      left:Integer;
      top:Integer;
      right:Integer;
      bottom:Integer;
end;


implementation

end.
