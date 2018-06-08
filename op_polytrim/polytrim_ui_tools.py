'''
Created on Oct 10, 2015

@author: Patrick
'''
from .. import common_utilities
from bpy_extras import view3d_utils

class Polytrim_UI_Tools():
    
    def sketch_confirm(self, context, eventd):
        
        #TODO  #OPTIMIZATION OPPORTUNITY
        #There is a lot of self.knife data manipilation happening at the Operator level
        #perhaps, self.knife needs some of these methods
        
        #self.knife.sketch_confirm(self.setch)
        
        #might make sense to hvae self.draw_sketch  -> self.knife?   Subclass of knife?
        
        #some logic related to closing the loop or extending the polyline from the first point.
        
        print('sketch confirmed')
        if len(self.sketch) < 5 and self.knife.ui_type == 'DENSE_POLY':
            print('sketch too short, cant confirm')
            return
        x,y = eventd['mouse']  #coordinates of where LeftMouse was released
        region = context.region
        rv3d = context.region_data
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, (x,y))  #get the direction under the mouse given the user 3DView perspective matrix
        
        hover_start = self.knife.hovered[1] #guaranteed to be a point by criteria to enter sketch mode
 
        self.knife.hover(context,x,y)  #hover again with current mouse location to see if we have re-entered the existing polyline
        #this will update the self.hovered property
        hover_end = self.knife.hovered[1]
   
        
        print('last hovered %i' % hover_start)
        
        sketch_3d = common_utilities.ray_cast_path(context, self.knife.cut_ob,self.sketch)  #at this moment we are going into 3D space, this returns world space locations
        new_pts = sketch_3d[0::5]

        if self.knife.hovered[0] == None:  #last hovered point is not a point or edge of polyline. User is not connecting back to polyline

            #add the points in at beginning of line
            if hover_start == 0: 
                self.knife.cyclic = False  # Correction for having set cyclic equal to True previously
                self.knife.pts = new_pts[::-1] + self.knife.pts[:]
                self.knife.normals = [view_vector]*len(sketch_3d[0::5]) + self.knife.normals 
                self.knife.pts = self.knife.pts[::-1]
                self.knife.normals = self.knife.normals[::-1]
            
            elif hover_start == len(self.knife.pts) - 1:
                self.knife.cyclic = False  # Correction for having set cyclic equal to True previously
               
                #add the 3d sketch points to the input points
                self.knife.pts += sketch_3d[0::5]   #filter out 4 out of 5 points to keep data density managable.  TODO, good opportunity for UI tuning>
                
                
                #store the view direction for cutting
                self.knife.normals += [view_vector]*len(sketch_3d[0::5]) #TODO optimize...don't slice twice, you are smart enough to calc this length!
                
            
            else:  #if the last hovered was not the endpoint of the polyline, need to trim and append
                self.knife.pts = self.knife.pts[:hover_start] + sketch_3d[0::5]
                self.knife.normals = self.knife.normals[:hover_start] + [view_vector]*len(sketch_3d[0::5])
                print('snipped off and added on to the tail')
        
        else:  # user is replacing a segment with a skecth because they initiaiated and terminated the sketch on the line.
            print('inserted new segment')
            print('last hovered is %i, now hovered %i' % (hover_start, self.knife.hovered[1]))
            
            if hover_start > self.knife.hovered[1]:  #drawing "upstream" relative to self.pts indexing, need to reverse the list unless
                
                if self.knife.hovered[1] == 0:
                    self.knife.pts = self.knife.pts[:hover_start] + new_pts
                    self.knife.normals = self.knife.normals[:hover_start] + [view_vector]*len(new_pts)
            
                else:
                    new_pts.reverse()
                    self.knife.pts = self.knife.pts[:self.knife.hovered[1]] + new_pts + self.knife.pts[hover_start:]
                    self.knife.normals = self.knife.normals[:self.knife.hovered[1]] + [view_vector]*len(new_pts) + self.knife.normals[hover_start:]
            
            else:
                if self.knife.hovered[1] == 0: #drew back into tail
                    self.knife.pts += sketch_3d[0::5]
                    self.knife.normals += [view_vector]*len(sketch_3d[0::5])
                    self.knife.cyclic = True
                else:
                    self.knife.pts = self.knife.pts[:hover_start] + new_pts + self.knife.pts[self.knife.hovered[1]:]
                    self.knife.normals = self.knife.normals[:hover_start]  + [view_vector]*len(new_pts) + self.knife.normals[self.knife.hovered[1]:]
        
        self.knife.snap_poly_line()  #why do this again?