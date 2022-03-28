/*
 * If not stated otherwise in this file or this component's Licenses.txt file the
 * following copyright and licenses apply:
 *
 * Copyright 2020 RDK Management
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
*/

#ifndef _WANMGR_INTERFACE_SM_H_
#define _WANMGR_INTERFACE_SM_H_
/* ---- Global Types -------------------------- */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <sys/time.h>
#include <time.h>
#include "wanmgr_rdkbus_common.h"
#include "wanmgr_data.h"

#define WAN_STATUS_UP   "up"
#define WAN_STATUS_DOWN "down"

#include <sysevent/sysevent.h>
extern int sysevent_fd;
extern token_t sysevent_token;

#ifdef FEATURE_IPOE_HEALTH_CHECK
typedef enum
{
    IHC_STOPPED = 0,
    IHC_STARTED
}wanmgr_ihc_status_t;
#endif

typedef enum
{
    WANMGR_IFACE_LINK_UP = 0,
    WANMGR_IFACE_LINK_DOWN,
    WANMGR_IFACE_CONNECTION_UP,
    WANMGR_IFACE_CONNECTION_DOWN,
    WANMGR_IFACE_CONNECTION_IPV6_UP,
    WANMGR_IFACE_CONNECTION_IPV6_DOWN,
#ifdef FEATURE_MAPT
    WANMGR_IFACE_MAPT_START,
    WANMGR_IFACE_MAPT_STOP,
#endif //FEATURE_MAPT
    WANMGR_IFACE_STATUS_ERROR
}wanmgr_iface_status_t;

typedef enum
{
    WAN_STATE_EXIT = 0,
    WAN_STATE_CONFIGURING_WAN,
    WAN_STATE_VALIDATING_WAN,
    WAN_STATE_OBTAINING_IP_ADDRESSES,
    WAN_STATE_IPV4_LEASED,
    WAN_STATE_IPV6_LEASED,
    WAN_STATE_DUAL_STACK_ACTIVE,
#ifdef FEATURE_MAPT
    WAN_STATE_MAPT_ACTIVE,
#endif //FEATURE_MAPT
    WAN_STATE_REFRESHING_WAN,
    WAN_STATE_DECONFIGURING_WAN
} eWanState_t;

typedef struct WanMgr_IfaceSM_Ctrl_st
{
    BOOL                    WanEnable;
    INT                     interfaceIdx;
#ifdef FEATURE_IPOE_HEALTH_CHECK
    UINT                    IhcPid;
    wanmgr_ihc_status_t     IhcV4Status;
    wanmgr_ihc_status_t     IhcV6Status;
#endif
    DML_WAN_IFACE*          pIfaceData;
    eWanState_t            eCurrentState; 
    DML_DEVICE_MODE         DeviceMode;
} WanMgr_IfaceSM_Controller_t;




void WanManager_UpdateInterfaceStatus(DML_WAN_IFACE* pIfaceData, wanmgr_iface_status_t iface_status);

void WanMgr_IfaceSM_Init(WanMgr_IfaceSM_Controller_t* pWanIfaceSMCtrl, INT iface_idx);
int WanMgr_StartInterfaceStateMachine(WanMgr_IfaceSM_Controller_t *wanIf);

#endif /*_WANMGR_INTERFACE_SM_H_*/
