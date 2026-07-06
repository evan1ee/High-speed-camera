using System;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using CaptureCard_Net;

namespace ResumeConnect
{
    internal class Program
    {
        private static CamDev cam = new CamDev();
        private static CardDev card = new CardDev();
        private const int INTERFACE = 1;
        private const int CAMERA = 0;
        private static IMVFGDefine.IMV_FG_FrameCallBack frameCallBack;
        private static IMVFGDefine.IMV_FG_ConnectCallBack connectCallBack;

        private static void Main(string[] args)
        {
            uint boardIndex = 0;
            int cameraIndex = 0;
            Console.WriteLine("SDK Version:{0}", CardDev.IMV_FG_GetVersion());
            Console.WriteLine("Enum capture board interface info.");
            //枚举采集卡设备
            // Discover capture board device
            int res = IMVFGDefine.IMV_FG_OK;
            IMVFGDefine.IMV_FG_INTERFACE_INFO_LIST interfaceList = new IMVFGDefine.IMV_FG_INTERFACE_INFO_LIST();
            IMVFGDefine.IMV_FG_EInterfaceType interfaceTp = IMVFGDefine.IMV_FG_EInterfaceType.typeInterfaceAll;

            res = CardDev.IMV_FG_EnumInterface((uint)interfaceTp, ref interfaceList);
            if (res != IMVFGDefine.IMV_FG_OK)
            {
                Console.WriteLine("Enumeration devices failed!errorCode:[{0}]", res);
                Console.Read();
                return;
            }
            if (interfaceList.nInterfaceNum == 0)
            {
                Console.WriteLine("No board device find.errorCode:[{0}]", res);
                Console.Read();
                return;
            }

            Console.WriteLine("Enum camera device.");
            IMVFGDefine.IMV_FG_DEVICE_INFO_LIST camListPtr = new IMVFGDefine.IMV_FG_DEVICE_INFO_LIST();
            //枚举相机设备
            // discover camera 
            res = CamDev.IMV_FG_EnumDevices((uint)interfaceTp, ref camListPtr);
            if (res != IMVFGDefine.IMV_FG_OK)
            {
                Console.WriteLine("Enumeration camera devices failed!errorCode:[{0}]", res);
                Console.Read();
                return;
            }
            if (camListPtr.nDevNum == 0)
            {
                Console.WriteLine("No camera device find.errorCode:[{0}]", res);
                Console.Read();
                return;
            }

            // 打印设备基本信息（序号,类型,制造商信息,型号,序列号,用户自定义ID)
            // Print device info (Index, Type, Vendor, Model, Serial number, DeviceUserID) 
            displayDeviceInfo(interfaceList, camListPtr);

            // 选择需要连接的采集卡设备开流
            // Select one camera to connect to  
            boardIndex = selectDevice(interfaceList.nInterfaceNum, camListPtr.nDevNum, INTERFACE);
            cameraIndex = (int)selectDevice(interfaceList.nInterfaceNum, camListPtr.nDevNum, CAMERA);

            do
            {
                // 获取选择的采集卡信息
                // Obtain the selected card information
                IMVFGDefine.IMV_FG_INTERFACE_INFO interfaceinfo =
                    (IMVFGDefine.IMV_FG_INTERFACE_INFO)
                        Marshal.PtrToStructure(
                            interfaceList.pInterfaceInfoList +
                            Marshal.SizeOf(typeof(IMVFGDefine.IMV_FG_INTERFACE_INFO)) * (int)boardIndex,
                            typeof(IMVFGDefine.IMV_FG_INTERFACE_INFO));

                // 获取选择的相机信息
                // Obtain the selected camera information
                IMVFGDefine.IMV_FG_DEVICE_INFO deviceinfo =
                        (IMVFGDefine.IMV_FG_DEVICE_INFO)
                            Marshal.PtrToStructure(
                                camListPtr.pDeviceInfoList +
                                Marshal.SizeOf(typeof(IMVFGDefine.IMV_FG_DEVICE_INFO)) * cameraIndex,
                                typeof(IMVFGDefine.IMV_FG_DEVICE_INFO));

                Console.WriteLine("Open capture device.");
                // 打开采集卡设备
                // Open capture device 
                res = card.IMV_FG_OpenInterfaceEx(IMVFGDefine.IMV_FG_ECreateHandleMode.IMV_FG_MODE_BY_CAMERAKEY, cameraStr: interfaceinfo.interfaceKey);
                if (res != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("Open cameralink capture board device failed!errorCode:[{0}]", res);
                    break;
                }

                Console.WriteLine("Open camera device.");
                // 打开采集卡相机设备 
                // Connect to CamDev 
                res = cam.IMV_FG_OpenDevice(IMVFGDefine.IMV_FG_ECreateHandleMode.IMV_FG_MODE_BY_CAMERAKEY, cameraStr: deviceinfo.cameraKey);
                if (res != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("Open camera failed!errorCode:[{0}]", res);
                    break;
                }

                // 自由拉流
                // set TriggerMode Off
                res = cam.IMV_FG_SetEnumFeatureSymbol("TriggerMode", "Off");
                if (res != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("Set TriggerMode failed! ErrorCode:[{0}]", res);
                    break;
                }

                // 设备连接状态事件回调函数
                // Device connection status event callback function
                connectCallBack = onDeviceLinkNotify;
                res = cam.IMV_FG_SubscribeConnectArg(connectCallBack, Marshal.StringToHGlobalAnsi(deviceinfo.cameraKey));
                if (res != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("SubscribeConnectArg failed! ErrorCode:[{0}]", res);
                    break;
                }

                // 数据帧回调函数
                // Data frame callback function
                frameCallBack = onGetFrame;
                res = cam.IMV_FG_AttachGrabbing(frameCallBack, IntPtr.Zero);
                if (res != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("AttachGrabbing failed! ErrorCode:[{0}]", res);
                    break;
                }

                // 开始拉流 
                // Start grabbing 
                res = cam.IMV_FG_StartGrabbing();
                if (res != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("Start grabbing failed! ErrorCode:[{0}]", res);
                    break;
                }

                Console.Read();
                g_isMainThreadExit = true;

                // 停止拉流 
                // Stop grabbing 
                res = cam.IMV_FG_StopGrabbing();
                if (res != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("Stop grabbing failed! ErrorCode:[{0}]", res);
                    break;
                }
            } while (false);

            Console.WriteLine("Close camera device.");
            if (cam.getHandle() != IntPtr.Zero)
            {
                //关闭相机
                //Close camera 
                res = cam.IMV_FG_CloseDevice();
                if (res != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("Close camera failed!");
                }
            }

            Console.WriteLine("Close capture device.");
            if (card.getHandle() != IntPtr.Zero)
            {
                // 关闭采集卡
                // Close capture device 
                res = card.IMV_FG_CloseInterface();
                if (res != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("Close cameralink board failed!");
                }
            }

            Console.WriteLine("Press enter key to exit...");
            Console.Read();
        }

        // 断线通知处理
        // offLine notify processing
        private static void deviceOffLine()
        {
            // 停止拉流 
            // Stop grabbing 
            cam.IMV_FG_StopGrabbing();
        }

        private static volatile bool g_isMainThreadExit = false;

        private static void deviceOnLine(string cameraKey)
        {
            // 关闭相机
            // Close camera 
            cam.IMV_FG_CloseDevice();

            int ret = IMVFGDefine.IMV_FG_OK;

            do
            {
                if (g_isMainThreadExit)
                {
                    return;
                }

                ret = cam.IMV_FG_OpenDevice(IMVFGDefine.IMV_FG_ECreateHandleMode.IMV_FG_MODE_BY_CAMERAKEY, cameraStr: cameraKey);
                if (ret != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("Retry open camera failed! ErrorCode[{0}]", ret);
                }
                else
                {
                    Console.WriteLine("Retry open camera successfully!");
                    break;
                }

                Thread.Sleep(500);

            } while (true);

            // 重新设备连接状态事件回调函数
            // Device connection status event callback function again
            connectCallBack = onDeviceLinkNotify;
            ret = cam.IMV_FG_SubscribeConnectArg(connectCallBack, Marshal.StringToHGlobalAnsi(cameraKey));
            if (ret != IMVFGDefine.IMV_FG_OK)
            {
                Console.WriteLine("SubscribeConnectArg failed! ErrorCode:[{0}]", ret);
            }

            // 重新注册数据帧回调函数
            // Register data frame callback function again
            frameCallBack = onGetFrame;
            ret = cam.IMV_FG_AttachGrabbing(frameCallBack, IntPtr.Zero);
            if (ret != IMVFGDefine.IMV_FG_OK)
            {
                Console.WriteLine("AttachGrabbing failed! ErrorCode:[{0}]", ret);
            }

            // 开始拉流 
            // Start grabbing 
            ret = cam.IMV_FG_StartGrabbing();
            if (ret != IMVFGDefine.IMV_FG_OK)
            {
                Console.WriteLine("Start grabbing failed! ErrorCode:[{0}]", ret);
            }

        }

        private static void onDeviceLinkNotify(ref IMVFGDefine.IMV_FG_SConnectArg pConnectArg, IntPtr pUser)
        {
            // 断线通知
            // offLine notify 
            if (pConnectArg.eventMsg == IMVFGDefine.IMV_FG_EVType.IMV_FG_OFFLINE)
            {
                Console.WriteLine("---------camera[{0}] : OffLine--------", Marshal.PtrToStringAnsi(pUser));
                deviceOffLine();
            }

            // 上线通知
            // onLine notify
            else if (pConnectArg.eventMsg == IMVFGDefine.IMV_FG_EVType.IMV_FG_ONLINE)
            {
                Console.WriteLine("---------camera[{0}] : OnLine--------", Marshal.PtrToStringAnsi(pUser));
                deviceOnLine(Marshal.PtrToStringAnsi(pUser));
            }
        }

        private static void onGetFrame(ref IMVFGDefine.IMV_FG_Frame frame, IntPtr pUser)
        {
            Console.WriteLine("Get frame blockId = {0}", frame.frameInfo.blockId);
        }

        private static uint selectDevice(uint interfaceCnt, uint cameraCnt, int devType)
        {
            if (devType == CAMERA) Console.Write("Please input the camera index: ");
            else Console.Write("Please input the interface index: ");
            int inputIndex;
            while (true)
            {
                inputIndex = 0;
                try
                {
                    inputIndex = Convert.ToInt32(Console.ReadLine()) - 1;
                }
                catch
                {
                    if (devType == INTERFACE)
                    {
                        Console.Write("Invalid Input!Please input the interface index: ");
                        continue;
                    }
                    else
                    {
                        Console.Write("Invalid Input!Please input the camera index: ");
                        continue;
                    }
                }
                if ((inputIndex > interfaceCnt - 1 || inputIndex < 0) && devType == INTERFACE)
                {
                    Console.Write("Input Error!Please input the interface index: ");
                    continue;
                }
                else if ((inputIndex > cameraCnt - 1 || inputIndex < 0) && devType == CAMERA)
                {
                    Console.Write("Input Error!Please input the camera index: ");
                    continue;
                }
                break;
            }

            return (uint)inputIndex;
        }

        #region 展示设备列表

        private static void displayDeviceInfo(IMVFGDefine.IMV_FG_INTERFACE_INFO_LIST interfaceInfoList,
             IMVFGDefine.IMV_FG_DEVICE_INFO_LIST deviceInfoList)
        {
            // 打印Title行 
            Console.WriteLine(
                "\nIdx    Type            Vendor                  Model                    S/N                        DeviceUserID                     ");
            Console.WriteLine(
                "--------------------------------------------------------------------------------------------------------------");

            for (int i = 0; i < interfaceInfoList.nInterfaceNum; i++)
            {
                string interfaceinfostr = string.Empty;
                IMVFGDefine.IMV_FG_INTERFACE_INFO interfaceinfo =
                    (IMVFGDefine.IMV_FG_INTERFACE_INFO)
                        Marshal.PtrToStructure(
                            interfaceInfoList.pInterfaceInfoList +
                            Marshal.SizeOf(typeof(IMVFGDefine.IMV_FG_INTERFACE_INFO)) * i,
                            typeof(IMVFGDefine.IMV_FG_INTERFACE_INFO));

                // 设备列表的相机索引  最大表示字数：3
                interfaceinfostr += (i + 1).ToString().PadRight(7);

                switch (interfaceinfo.nInterfaceType)
                {
                    case IMVFGDefine.IMV_FG_EInterfaceType.typeGigEInterface:
                        interfaceinfostr += "GigE Card".PadRight(15);
                        break;
                    case IMVFGDefine.IMV_FG_EInterfaceType.typeU3vInterface:
                        interfaceinfostr += "U3V Card".PadRight(15);
                        break;
                    case IMVFGDefine.IMV_FG_EInterfaceType.typeCLInterface:
                        interfaceinfostr += "CL Card".PadRight(15);
                        break;
                    case IMVFGDefine.IMV_FG_EInterfaceType.typeCXPInterface:
                        interfaceinfostr += "CXP Card".PadRight(15);
                        break;
                    default:
                        interfaceinfostr += " ".PadRight(15);
                        break;
                }

                // 制造商信息  
                interfaceinfostr += interfaceinfo.vendorName.PadRight(25);

                // 相机的型号信息  
                interfaceinfostr += interfaceinfo.modelName.PadRight(25);

                // 相机的序列号 
                interfaceinfostr += interfaceinfo.serialNumber.PadRight(27);

                // 自定义用户ID 
                interfaceinfostr += interfaceinfo.interfaceName.PadRight(20);

                Console.WriteLine(interfaceinfostr);
                Console.Write("       |--");

                bool isFind = false;
                for (int j = 0; j < deviceInfoList.nDevNum; j++)
                {
                    string deviceinfostr = string.Empty;
                    IMVFGDefine.IMV_FG_DEVICE_INFO deviceinfo =
                        (IMVFGDefine.IMV_FG_DEVICE_INFO)
                            Marshal.PtrToStructure(
                                deviceInfoList.pDeviceInfoList +
                                Marshal.SizeOf(typeof(IMVFGDefine.IMV_FG_DEVICE_INFO)) * j,
                                typeof(IMVFGDefine.IMV_FG_DEVICE_INFO));

                    if (deviceinfo.FGInterfaceInfo.interfaceKey.Equals(interfaceinfo.interfaceKey))
                    {
                        // 设备列表的相机索引  最大表示字数：3
                        deviceinfostr += (j + 1).ToString().PadRight(12);

                        // 制造商信息  
                        deviceinfostr += deviceinfo.vendorName.PadRight(25);

                        // 相机的型号信息  
                        deviceinfostr += deviceinfo.modelName.PadRight(25);

                        // 相机的序列号 
                        deviceinfostr += deviceinfo.serialNumber.PadRight(27);

                        // 自定义用户ID 
                        deviceinfostr += deviceinfo.cameraName.PadRight(20);

                        Console.WriteLine(deviceinfostr);
                        isFind = true;
                        break;
                    }
                }

                if (!isFind) Console.WriteLine();
            }
        }

        #endregion
    }
}
