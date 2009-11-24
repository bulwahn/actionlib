#! /usr/bin/env python
# Copyright (c) 2009, Willow Garage, Inc.
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the Willow Garage, Inc. nor the names of its
#       contributors may be used to endorse or promote products derived from
#       this software without specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# Author: Alexander Sorokin. 
# Based on C++ simple_action_server.h by Eitan Marder-Eppstein
from __future__ import with_statement

import roslib; roslib.load_manifest('actionlib')
import rospy

import threading

from actionlib_msgs.msg import *

from actionlib import ActionServer
from actionlib.server_goal_handle import ServerGoalHandle;

def nop_cb(goal_handle):
    pass


class SimpleActionServer:
    """
    The SimpleActionServer
    implements a singe goal policy on top of the ActionServer class. The
    specification of the policy is as follows: only one goal can have an
    active status at a time, new goals preempt previous goals based on the
    stamp in their GoalID field (later goals preempt earlier ones), an
    explicit preempt goal preempts all goals with timestamps that are less
    than or equal to the stamp associated with the preempt, accepting a new
    goal implies successful preemption of any old goal and the status of the
    old goal will be change automatically to reflect this.
    """

    def __init__(self, name, ActionSpec, execute_cb = None, auto_start = True):
        """
        Constructor for a SimpleActionServer
        @param name A name for the action server
        @param execute_cb Optional callback that gets called in a separate thread whenever
               a new goal is received, allowing users to have blocking callbacks.
               Adding an execute callback also deactivates the goalCallback.
        @param  auto_start A boolean value that tells the ActionServer wheteher or not to start publishing as soon as it comes up
        """

        self.new_goal = False
        self.preempt_request = False
        self.new_goal_preempt_request = False

        self.execute_callback = execute_cb;
        self.goal_callback = None;
        self.preempt_callback = None;

        self.need_to_terminate = False
        self.terminate_mutex = threading.RLock();
        self.lock = threading.RLock();

        self.execute_condition = threading.Condition(self.lock);

        self.current_goal = ServerGoalHandle();
        self.next_goal = ServerGoalHandle();

        #create the action server
        self.action_server = ActionServer(name, ActionSpec, self.internal_goal_callback,self.internal_preempt_callback,auto_start);
        if self.execute_callback:
            self.execute_thread = threading.Thread(None, self.executeLoop);
            self.execute_thread.start();
        else:
            self.execute_thread = None


    def __del__(self):
        if self.execute_callback:
            with self.terminate_mutex:
                self.need_to_terminate = True;

            assert(self.execute_thread);
            self.execute_thread.join();


    def accept_new_goal(self):
        """
        Accepts a new goal when one is available The status of this
        goal is set to active upon acceptance, and the status of any
        previously active goal is set to preempted. Preempts received for the
        new goal between checking if isNewGoalAvailable or invokation of a
        goal callback and the acceptNewGoal call will not trigger a preempt
        callback.  This means, isPreemptReqauested should be called after
        accepting the goal even for callback-based implementations to make
        sure the new goal does not have a pending preempt request.
        @return A shared_ptr to the new goal.
        """

        with self.lock:
            if not self.new_goal or not self.next_goal.get_goal():
                rospy.logerr("Attempting to accept the next goal when a new goal is not available");
                return None;

        #check if we need to send a preempted message for the goal that we're currently pursuing
        if self.is_active() and self.current_goal.get_goal() and self.current_goal != self.next_goal:
            self.current_goal.set_canceled();
        
        rospy.logdebug("Accepting a new goal");

        #accept the next goal
        self.current_goal = self.next_goal;
        self.new_goal = False;

        #set preempt to request to equal the preempt state of the new goal
        self.preempt_request = self.new_goal_preempt_request;
        self.new_goal_preempt_request = False;

        #set the status of the current goal to be active
        self.current_goal.set_accepted();

        return self.current_goal.get_goal();


    def is_new_goal_available(self):
        """
        Allows  polling implementations to query about the availability of a new goal
        @return True if a new goal is available, false otherwise
        """
        return self.new_goal;


    def is_preempt_requested(self):
        """
        Allows  polling implementations to query about preempt requests
        @return True if a preempt is requested, false otherwise
        """
        return self.preempt_request;

    def is_active(self):
       """
       Allows  polling implementations to query about the status of the current goal
       @return True if a goal is active, false otherwise
       """
       if not self.current_goal.get_goal():
           return False;

       status = self.current_goal.get_goal_status().status;
       return status == actionlib_msgs.msg.GoalStatus.ACTIVE or status == actionlib_msgs.msg.GoalStatus.PREEMPTING;

    def set_succeeded(self,result=None):
      """
      Sets the status of the active goal to succeeded
      @param  result An optional result to send back to any clients of the goal
      """
      with self.lock:
          if not result:
              result=self.get_default_result();
          self.current_goal.set_succeeded(result);

    def set_aborted(self, result = None):
        """
        Sets the status of the active goal to aborted
        @param  result An optional result to send back to any clients of the goal
        """
        with self.lock:
            if not result:
                result=self.get_default_result();
            self.current_goal.set_aborted(result);

    def publish_feedback(self,feedback):
        """
        Publishes feedback for a given goal
        @param  feedback Shared pointer to the feedback to publish
        """
        self.current_goal.publish_feedback(feedback);


    def get_default_result(self):
        return self.action_server.ActionResultType();

    def set_preempted(self,result=None):
        """
        Sets the status of the active goal to preempted
        @param  result An optional result to send back to any clients of the goal
        """
        if not result:
            result=self.get_default_result();
        with self.lock:
            rospy.logdebug("Setting the current goal as canceled");
            self.current_goal.set_canceled(result);

    def register_goal_callback(self,cb):
        """
        Allows users to register a callback to be invoked when a new goal is available
        @param cb The callback to be invoked
        """
        if self.execute_callback:
            rospy.logwarn("Cannot call SimpleActionServer.register_goal_callback() because an executeCallback exists. Not going to register it.");
        else:
            self.goal_callback = cb;

    def register_preempt_callback(self, cb):
        """
        Allows users to register a callback to be invoked when a new preempt request is available
        @param cb The callback to be invoked
        """
        self.preempt_callback = cb;          
            

    def start(self):
        """
        Explicitly start the action server, used it auto_start is set to false
        """
        self.action_server.start();
        
        
    def internal_goal_callback(self, goal):
          """
          Callback for when the ActionServer receives a new goal and passes it on
          """
          self.execute_condition.acquire();

          try:
              rospy.logdebug("A new goal %shas been recieved by the single goal action server",goal.get_goal_id().id);

              #check that the timestamp is past that of the current goal and the next goal
              if((not self.current_goal.get_goal() or goal.get_goal_id().stamp > self.current_goal.get_goal_id().stamp)
                 and (not self.next_goal.get_goal() or goal.get_goal_id().stamp > self.next_goal.get_goal_id().stamp)):
                  #if next_goal has not been accepted already... its going to get bumped, but we need to let the client know we're preempting
                  if(self.next_goal.get_goal() and (not self.current_goal.get_goal() or self.next_goal != self.current_goal)):
                      self.next_goal.set_canceled();
                  
                  self.next_goal = goal;
                  self.new_goal = True;
                  self.new_goal_preempt_request = False;

                  #if the server is active, we'll want to call the preempt callback for the current goal
                  if(self.is_active()):
                      self.preempt_request = True;
                      #if the user has registered a preempt callback, we'll call it now
                      if(self.preempt_callback):
                          self.preempt_callback();

                  #if the user has defined a goal callback, we'll call it now
                  if self.goal_callback:
                      self.goal_callback();
                  
                  #Trigger runLoop to call execute()
                  self.execute_condition.notify();
                  self.execute_condition.release();
              else:
                  #the goal requested has already been preempted by a different goal, so we're not going to execute it
                  goal.set_canceled();
                  self.execute_condition.release();
          except e:
              rospy.logerr("SimpleActionServer.internal_goal_callback - exception %s",str(e))
              self.execute_condition.release();

    def internal_preempt_callback(self,preempt):
          """
          Callback for when the ActionServer receives a new preempt and passes it on
          """
          with self.lock:
              rospy.logdebug("A preempt has been received by the SimpleActionServer");

              #if the preempt is for the current goal, then we'll set the preemptRequest flag and call the user's preempt callback
              if(preempt == self.current_goal):
                  rospy.logdebug("Setting preempt_request bit for the current goal to TRUE and invoking callback");
                  self.preempt_request = True;

                  #if the user has registered a preempt callback, we'll call it now
                  if(self.preempt_callback):
                      self.preempt_callback();
              #if the preempt applies to the next goal, we'll set the preempt bit for that
              elif(preempt == self.next_goal):
                  rospy.logdebug("Setting preempt request bit for the next goal to TRUE");
                  self.new_goal_preempt_request = True;

    def executeLoop(self):
          """
          Called from a separate thread to call blocking execute calls
          """
          loop_duration = rospy.Duration.from_seconds(.1);

          while (not rospy.is_shutdown()):
              rospy.logdebug("SAS: execute");

              with self.terminate_mutex:
                  if (self.need_to_terminate):
                      break;

              shall_run=False;
              with self.lock:
                  if (self.is_active()):
                      rospy.logerr("Should never reach this code with an active goal");
                      return
                  elif (self.is_new_goal_available()):
                      goal = self.accept_new_goal();
                      if not self.execute_callback:
                          rospy.logerr("execute_callback_ must exist. This is a bug in SimpleActionServer");
                          return
                      shall_run=True

              if shall_run:
                  self.execute_callback(goal)

              self.execute_condition.acquire();
              if (self.is_active()):
                  rospy.logwarn("Your executeCallback did not set the goal to a terminal status.\n"+
                                "This is a bug in your ActionServer implementation. Fix your code!\n"+
                                "For now, the ActionServer will set this goal to aborted");
                  self.set_aborted();
              self.execute_condition.wait(loop_duration.to_sec());
              self.execute_condition.release();


