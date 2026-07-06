using System;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Threading;
using CaptureCard_Net;

namespace GrabAsynchronous
{
    internal class Program
    {
        public static CamDev cam = new CamDev();
        public static CardDev card = new CardDev();
        public static readonly int Max_Count = 2;              //ch:队列缓存区大小,可根据实际情况调整大小 en:The size of the queue cache area can be adjusted according to the actual situation
        public static IMVFGDefine.IMV_FG_FrameCallBack frameCallBack;
        public volatile static bool g_isExitThread = false;
        private const int INTERFACE = 1;
        private const int CAMERA = 0;

        /// <summary>
        /// 指针之间进行数据拷贝
        /// </summary>
        /// <param name="pDst">目标地址</param>
        /// <param name="pSrc">源地址</param>
        /// <param name="len">拷贝数据长度</param>
        [DllImport("Kernel32.dll", EntryPoint = "RtlMoveMemory")]
        internal static extern void CopyMemory(IntPtr pDst, IntPtr pSrc, int len);
        public struct FrameInfo
        {
            public ulong blockId;    // 帧 ID / Frame ID
            public uint width;       // 宽度 / Width
            public uint height;      // 高度 / Height
            public uint size;        // 数据大小 / Data size
            public IntPtr data;      // 非托管内存指针 / Unmanaged memory pointer
        }

        public class FrameQueue : IDisposable
        {
            private FrameInfo[] qFrames;
            private int qCurrentSize;
            private int start;
            private int end;
            private int qMaxlen;
            private bool disposed = false;
            private uint frameBufferSize;
            private object lockObj = new object();

            public FrameQueue()
            {
                qCurrentSize = 0;
                start = 0;
                end = 0;
                qMaxlen = 0;
                qFrames = null;
                frameBufferSize = 0;
            }

            /// <summary>
            /// 初始化帧队列
            /// Initialize the frame queue
            /// </summary>
            /// <param name="nBufCount">缓冲区帧数量 / Number of buffer frames</param>
            /// <param name="nImageSize">每帧图像大小（字节）/ Size of each image (bytes)</param>
            /// <returns>0=成功，-1=失败 / 0=Success, -1=Failure</returns>
            public int Initialize(int nBufCount, uint nImageSize)
            {
                if (nBufCount <= 0 || nImageSize == 0)
                {
                    Console.WriteLine("Invalid buffer count or image size.");
                    return -1;
                }
                ReleaseUnmanagedResources();

                qMaxlen = nBufCount;
                qFrames = new FrameInfo[nBufCount];
                frameBufferSize = nImageSize;

                for (int i = 0; i < nBufCount; i++)
                {
                    qFrames[i].width = 0;
                    qFrames[i].height = 0;
                    qFrames[i].blockId = 0;
                    qFrames[i].size = 0;
                    qFrames[i].data = Marshal.AllocHGlobal((int)nImageSize);
                    if (qFrames[i].data == IntPtr.Zero)
                    {
                        ReleaseUnmanagedResources();
                        Console.WriteLine("qFrames is null");
                        return -1;
                    }
                }
                qCurrentSize = 0;
                start = 0;
                end = 0;
                return 0;
            }

            /// <summary>
            /// 释放所有非托管内存
            /// Release all unmanaged memory
            /// </summary>
            private void ReleaseUnmanagedResources()
            {
                if (qFrames != null)
                {
                    for (int i = 0; i < qFrames.Length; i++)
                    {
                        if (qFrames[i].data != IntPtr.Zero)
                        {
                            Marshal.FreeHGlobal(qFrames[i].data);
                            qFrames[i].data = IntPtr.Zero;
                        }
                    }
                    qFrames = null;
                }
            }

            /// <summary>
            /// 向队列推入一帧图像
            /// Push a frame into the queue
            /// </summary>
            /// <param name="nBlockID">帧 ID / Frame ID</param>
            /// <param name="nWidth">图像宽度 / Width</param>
            /// <param name="nHeight">图像高度 / Height</param>
            /// <param name="pData">源图像数据指针 / Source image data pointer</param>
            /// <param name="nSize">数据大小 / Data size</param>
            /// <returns>0=成功，-1=失败</returns>
            public int push(ulong nBlockID, uint nWidth, uint nHeight, IntPtr pData, uint nSize)
            {
                if (pData == IntPtr.Zero || nSize == 0)
                {
                    Console.WriteLine("Invalid input data in Push");
                    return -1;
                }

                lock (lockObj)
                {
                    if (qCurrentSize == qMaxlen)
                    {
                        Console.WriteLine("There are no empty positions in the queue");
                        return -1;
                    }

                    if (nSize > frameBufferSize)
                    {
                        Console.WriteLine("Input data size exceeds frame buffer size.");
                        return -1;
                    }

                    qFrames[end].blockId = nBlockID;
                    qFrames[end].width = nWidth;
                    qFrames[end].height = nHeight;
                    qFrames[end].size = nSize;

                    if (qFrames[end].data != IntPtr.Zero)
                    {
                        CopyMemory(qFrames[end].data, pData, (int)nSize);
                    }
                    else
                    {
                        Console.WriteLine("data invalid");
                        return -1;
                    }

                    end = (end + 1) % qMaxlen;
                    qCurrentSize++;
                    return 0;
                }
            }

            /// <summary>
            /// 从队列弹出一帧图像
            /// </summary>
            /// <param name="frame">输出帧信息</param>
            /// <param name="pData">目标缓冲区（必须足够大）</param>
            /// <param name="bufSize">目标缓冲区大小</param>
            /// <returns>0=成功, -1=队列空, -2=缓冲区太小</returns>
            public int pop(ref FrameInfo frame, IntPtr pData, uint bufSize)
            {
                if (pData == IntPtr.Zero)
                {
                    Console.WriteLine("Destination pointer is null in Pop");
                    return -1;
                }

                lock (lockObj)
                {

                    if (qCurrentSize == 0)
                    {
                        Console.WriteLine("The queue has no data");
                        return -1;
                    }

                    uint size = qFrames[start].size;
                    if (bufSize < size)
                    {
                        Console.WriteLine("Destination buffer too small in Pop");
                        return -2;
                    }

                    frame.blockId = qFrames[start].blockId;
                    frame.width = qFrames[start].width;
                    frame.height = qFrames[start].height;
                    frame.size = qFrames[start].size;

                    if (qFrames[start].data != IntPtr.Zero)
                    {
                        CopyMemory(pData, qFrames[start].data, (int)qFrames[start].size);
                    }
                    else
                    {
                        Console.WriteLine("data is null");
                        return -1;
                    }
                    qCurrentSize--;
                    start = (start + 1) % qMaxlen;
                    return 0;
                }
            }

            #region IDisposable Support
            protected virtual void Dispose(bool disposing)
            {
                if (!disposed)
                {
                    ReleaseUnmanagedResources();

                    if (disposing)
                    {
                    }

                    disposed = true;
                }
            }

            public void Dispose()
            {
                Dispose(true);
                GC.SuppressFinalize(this);
            }
            #endregion
        }

        public static FrameQueue m_queue;

        private static void Main(string[] args)
        {
            m_queue = new FrameQueue();
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
                Console.WriteLine("Open capture device.");
                // 打开采集卡设备
                // Open capture device 
                res = card.IMV_FG_OpenInterface(boardIndex);
                if (res != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("Open cameralink capture board device failed!errorCode:[{0}]", res);
                    break;
                }

                Console.WriteLine("Open camera device.");
                // 打开采集卡相机设备 
                // Connect to CamDev 
                res = cam.IMV_FG_OpenDevice(IMVFGDefine.IMV_FG_ECreateHandleMode.IMV_FG_MODE_BY_INDEX, cameraIndex);
                if (res != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("Open camera failed!errorCode:[{0}]", res);
                    break;
                }

                // 计算帧大小
                // Calculate frame size
                uint nImageSize = 0;
                res = getFrameSize(ref nImageSize);
                if (res != IMVFGDefine.IMV_FG_OK || nImageSize <= 0)
                {
                    break;
                }

                //初始化队列
                //Initiation queue
                res = m_queue.Initialize(Max_Count, nImageSize);
                if (res != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("Init frameQueue failed! ErrorCode[{0}]", res);
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

                // 注册数据帧回调函数
                // Register data frame callback function
                frameCallBack = new IMVFGDefine.IMV_FG_FrameCallBack(onGetFrame);
                res = cam.IMV_FG_AttachGrabbing(frameCallBack, IntPtr.Zero);
                if (res != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("Attach grabbing failed! ErrorCode:[{0}]", res);
                    break;
                }

                Task task = new Task(() => getFrameProc(nImageSize));
                task.Start();

                // 开始拉流 
                // Start grabbing 
                res = cam.IMV_FG_StartGrabbing();
                if (res != IMVFGDefine.IMV_FG_OK)
                {
                    Console.WriteLine("Start grabbing failed! ErrorCode:[{0}]", res);
                    break;
                }

                Thread.Sleep(2000);
                g_isExitThread = true;
                task.Wait();

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

            m_queue.Dispose();
            m_queue = null;
            Console.WriteLine("Press enter to exit");
            Console.Read();
        }

        private static int getFrameSize(ref uint nImageSize)
        {
            long width = 0, height = 0;

            int res = cam.IMV_FG_GetIntFeatureValue("Width", ref width);
            if (res != IMVFGDefine.IMV_FG_OK)
            {
                Console.WriteLine("Get width feature value failed! ErrorCode:[{0}]", res);
                return res;
            }

            res = cam.IMV_FG_GetIntFeatureValue("Height", ref height);
            if (res != IMVFGDefine.IMV_FG_OK)
            {
                Console.WriteLine("Get height feature value failed! ErrorCode:[{0}]", res);
                return res;
            }

            // 最合适的大小为(宽*高*每个像素占用的字节大小),此处申请源数据为RGB等彩色格式所需大小
            // The most suitable size is (width * height * (byte size occupied by each pixel))
            // The requested source data here is in the required size for color formats such as RGB
            nImageSize = (uint)width * (uint)height * 3;

            return IMVFGDefine.IMV_FG_OK;
        }

        private static void onGetFrame(ref IMVFGDefine.IMV_FG_Frame frame, IntPtr pUser)
        {
            int nRet = IMVFGDefine.IMV_FG_OK;
            if (frame.frameHandle == IntPtr.Zero)
            {
                Console.WriteLine("frame is NULL");
                return;
            }

            nRet = m_queue.push(frame.frameInfo.blockId, frame.frameInfo.width, frame.frameInfo.height, frame.pData,
                frame.frameInfo.size);
            if (nRet != 0)
            {
                Console.WriteLine("Add frame to queue failed! blockId is {0}", frame.frameInfo.blockId);
            }
            else
            {
                Console.WriteLine("Add frame to queue success! blockId is {0}", frame.frameInfo.blockId);
            }
        }

        private static void getFrameProc(uint nImageSize)
        {
            int res = 0;
            FrameInfo frame = new FrameInfo();
            frame.data = Marshal.AllocHGlobal((int)nImageSize);

            while (!g_isExitThread)
            {
                frame.blockId = 0;
                frame.width = 0;
                frame.height = 0;
                frame.size = 0;
                res = m_queue.pop(ref frame, frame.data, nImageSize);
                if (res != 0)
                {
                    Console.WriteLine("Pop failed, maybe no data.");
                    Thread.Sleep(1);
                    continue;
                }
                else
                {
                    Console.WriteLine("Pop success. BlockId is [{0}]", frame.blockId);
                }
            }

            Marshal.FreeHGlobal(frame.data);
            frame.data = IntPtr.Zero;
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
