using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using CaptureCard_Net;

namespace MultipleCamera
{
    class Device
    {
        private Thread m_hReceiveThread = null;         // 显示线程 | image display thread 
        private volatile bool m_bStartGrabbing = true;            // 线程控制变量 | thread looping flag 
        private Render m_Render = null;
        private CamDev camera = new CamDev();
        private CardDev card = new CardDev();
        private IntPtr m_pDstData = IntPtr.Zero;
        private int m_iDstDataSize = 0;
        private bool bOpen = false;

        public Device(Render render)
        {
            m_Render = render;
            m_Render.Open();
            m_stopWatch.Start();
        }

        // 打开采集卡和相机(使用对应的相机和卡的CameraKey)
        // Open the card and camera (using the corresponding camera and card's CameraKey)
        public bool Open(string cardKey, string cameraKey)
        {

            // 打开采集卡设备
            // Connect to card
            int res = card.IMV_FG_OpenInterfaceEx(IMVFGDefine.IMV_FG_ECreateHandleMode.IMV_FG_MODE_BY_CAMERAKEY, cameraStr: cardKey);
            if (res != IMVFGDefine.IMV_FG_OK)
            {
                MessageBox.Show("Open camera failed!");
                return false;
            }

            // 打开采集卡相机设备 
            // Connect to camera 
            res = camera.IMV_FG_OpenDevice(IMVFGDefine.IMV_FG_ECreateHandleMode.IMV_FG_MODE_BY_CAMERAKEY, cameraStr: cameraKey);
            if (res != IMVFGDefine.IMV_FG_OK)
            {
                MessageBox.Show("Open camera failed!");
                return false;
            }

            // 自由拉流
            // set TriggerMode Off
            res = camera.IMV_FG_SetEnumFeatureSymbol("TriggerMode", "Off");
            if (res != IMVFGDefine.IMV_FG_OK)
            {
                MessageBox.Show("Set enum feature value failed!");
                return false;
            }

            // 开始拉流 
            // Start grabbing
            res = camera.IMV_FG_StartGrabbing();
            if (res != IMVFGDefine.IMV_FG_OK)
            {
                MessageBox.Show("Start grabbing failed!");
                return false;
            }

            m_bStartGrabbing = true;
            m_hReceiveThread = new Thread(new ThreadStart(ShowThread));
            m_hReceiveThread.Start();

            bOpen = true;
            return true;

        }

        public bool Close()
        {
            m_bStartGrabbing = false;

            // 停止拉流 
            // Stop grabbing 
            int res = camera.IMV_FG_StopGrabbing();
            if (res != IMVFGDefine.IMV_FG_OK)
            {
                MessageBox.Show("Stop grabbing failed!");
                return false;
            }

            if (m_hReceiveThread != null)
                m_hReceiveThread.Join();

            // 关闭相机
            // Close camera 
            res = camera.IMV_FG_CloseDevice();
            if (res != IMVFGDefine.IMV_FG_OK)
            {
                MessageBox.Show("Close camera failed!");
                return false;
            }

            // 关闭采集卡
            // Close capture device 
            res = card.IMV_FG_CloseInterface();
            if (res != IMVFGDefine.IMV_FG_OK)
            {
                MessageBox.Show("Close cameralink board failed!");
                return false;
            }

            bOpen = false;
            return true;
        }

        // 转码显示线程 
        // display thread routine 
        private void ShowThread()
        {
            IMVFGDefine.IMV_FG_Frame frame = new IMVFGDefine.IMV_FG_Frame();
            int res = IMVFGDefine.IMV_FG_OK;
            while (m_bStartGrabbing)
            {
                // 获取一帧图像
                // Get a frame image 
                res = camera.IMV_FG_GetFrame(ref frame, 1000);
                if (res == IMVFGDefine.IMV_FG_OK)
                {
                    // 控制显示最高帧率为25FPS 
                    // control frame display rate to be 25 FPS 
                    if (true == isTimeToDisplay())
                    {
                        if (frame.frameInfo.pixelFormat == IMVFGDefine.IMV_FG_EPixelType.IMV_FG_PIXEL_TYPE_Mono8)
                        {
                            m_Render.Display(frame.pData, (int)frame.frameInfo.width, (int)frame.frameInfo.height,
                                Render.VR_PIXEL_TYPE_E.VR_PIXEL_FMT_MONO8);
                        }
                        else
                        {
                            if (ConvertToBGR24(ref frame))
                                m_Render.Display(m_pDstData, (int)frame.frameInfo.width, (int)frame.frameInfo.height,
                                    Render.VR_PIXEL_TYPE_E.VR_PIXEL_FMT_RGB24);
                        }
                    }

                    // 必须调用IMV_FG_ReleaseFrame()主动释放缓存
                    // Must call IMV_FG_ReleaseFrame() to actively release the cache
                    camera.IMV_FG_ReleaseFrame(ref frame);
                }


            }
        }

        //转码函数
        //transcoding function
        private bool ConvertToBGR24(ref IMVFGDefine.IMV_FG_Frame frame)
        {
            IMVFGDefine.IMV_FG_PixelConvertParam stPixelConvertParam = new IMVFGDefine.IMV_FG_PixelConvertParam();

            //当内存申请失败，返回false
            try
            {
                if (m_pDstData == IntPtr.Zero || frame.frameInfo.size * 3 > m_iDstDataSize)
                {
                    if (m_pDstData != IntPtr.Zero)
                    {
                        Marshal.FreeHGlobal(m_pDstData);
                        m_pDstData = IntPtr.Zero;
                    }
                    m_pDstData = Marshal.AllocHGlobal((int)frame.frameInfo.size * 3);
                    m_iDstDataSize = (int)frame.frameInfo.size * 3;
                }
            }
            catch
            {
                if (m_pDstData != IntPtr.Zero)
                {
                    Marshal.FreeHGlobal(m_pDstData);
                    m_pDstData = IntPtr.Zero;
                }
                m_iDstDataSize = 0;
                return false;
            }

            // 图像转换成BGR8
            // convert image to BGR8
            stPixelConvertParam.nWidth = frame.frameInfo.width;
            stPixelConvertParam.nHeight = frame.frameInfo.height;
            stPixelConvertParam.ePixelFormat = frame.frameInfo.pixelFormat;
            stPixelConvertParam.pSrcData = frame.pData;
            stPixelConvertParam.nSrcDataLen = frame.frameInfo.size;
            stPixelConvertParam.nPaddingX = frame.frameInfo.paddingX;
            stPixelConvertParam.nPaddingY = frame.frameInfo.paddingY;
            stPixelConvertParam.eBayerDemosaic = IMVFGDefine.IMV_FG_EBayerDemosaic.IMV_FG_DEMOSAIC_EDGE_SENSING;
            stPixelConvertParam.eDstPixelFormat = IMVFGDefine.IMV_FG_EPixelType.IMV_FG_PIXEL_TYPE_BGR8;
            stPixelConvertParam.pDstBuf = m_pDstData;
            stPixelConvertParam.nDstBufSize = (uint)m_iDstDataSize;

            int res = camera.IMV_FG_PixelConvert(ref stPixelConvertParam);
            if (res == IMVFGDefine.IMV_FG_OK) return true;
            return false;
        }

        public void Dispose()
        {
            if (bOpen) Close();
            m_bStartGrabbing = false;
            if (m_hReceiveThread != null)
                m_hReceiveThread.Join();
            if (m_pDstData != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(m_pDstData);
                m_pDstData = IntPtr.Zero;
            }
            m_Render.Close();
            m_Render = null;

        }

        const int DEFAULT_INTERVAL = 40;
        Stopwatch m_stopWatch = new Stopwatch();

        // 判断是否应该做显示操作 
        // calculate interval to determine if it's show time now 
        private bool isTimeToDisplay()
        {
            m_stopWatch.Stop();
            long m_lDisplayInterval = m_stopWatch.ElapsedMilliseconds;
            if (m_lDisplayInterval <= DEFAULT_INTERVAL)
            {
                m_stopWatch.Start();
                return false;
            }
            else
            {
                m_stopWatch.Reset();
                m_stopWatch.Start();
                return true;
            }
        }
    }
}
