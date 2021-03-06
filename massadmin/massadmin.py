#coding=utf-8
#--- Author: Dmitri Patrakov <traditio@gmail.com>
"""
Copyright (c) 2010, Stanislaw Adaszewski
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of Stanislaw Adaszewski nor the
      names of any contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL Stanislaw Adaszewski BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

from django.contrib import admin
from django.conf.urls.defaults import *
from django.core.exceptions import PermissionDenied
from django.db import transaction, models
from django.contrib.admin.util import unquote
from django.contrib.admin import helpers
from django.utils.translation import ugettext as _
from django.utils.encoding import force_unicode
from django.utils.safestring import mark_safe
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404, HttpResponseRedirect
from django.utils.html import escape
from django.contrib.contenttypes.models import ContentType
from django import  template
from django.shortcuts import render_to_response
from django.views.generic.simple import redirect_to
from django.forms.formsets import all_valid
# import new

urls = patterns('',
    (r'(?P<app_name>[a-z]+)/(?P<model_name>[a-z]+)-masschange/(?P<object_ids>[0-9,]+)/$', 'massadmin.massadmin.mass_change_view'),
    # (r'(?P<whatever>.*)', 'massadmin.massadmin.redirect_to_admin')
)

def redirect_to_admin(request, whatever):
    return redirect_to(request, url = 'admin/%s' % whatever)

#noinspection PyUnusedLocal
def mass_change_selected(modeladmin, request, queryset):
    # print request.POST
    selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
    return redirect_to(request, url = '../%s-masschange/%s' % (modeladmin.model._meta.module_name, ','.join(selected)))
mass_change_selected.short_description = u'Массовое редактирование'

def mass_change_view(request, app_name, model_name, object_ids):
    model = models.get_model(app_name, model_name)
    ma = MassAdmin(model, admin.site)
    return ma.mass_change_view(request, object_ids)

#noinspection PyRedeclaration
mass_change_view = staff_member_required(mass_change_view)

class MassAdmin(admin.ModelAdmin):
    def __init__(self, model, admin_site):
        try:
            self.admin_obj = admin_site._registry[model]
        except KeyError:
            raise('Model not registered with the admin site.')
        for (varname, var) in self.admin_obj.__class__.__dict__.iteritems():
            if not (varname.startswith('_') or callable(var)):
                self.__dict__[varname] = var
        super(MassAdmin, self).__init__(model, admin_site)
                        		
    def response_change(self, request, obj):
        """
        Determines the HttpResponse for the change_view stage.
        """
        opts = obj._meta

        msg = _('Selected %(name)s were changed successfully.') % {'name': force_unicode(opts.verbose_name_plural), 'obj': force_unicode(obj)}

        self.message_user(request, msg)
        return HttpResponseRedirect("../../%s/" % self.model._meta.module_name)
                        		
    def render_mass_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        opts = self.model._meta
        app_label = opts.app_label
        ordered_objects = opts.get_ordered_objects()
        context.update({
            'add': add,
            'change': change,
            'has_add_permission': self.has_add_permission(request),
            'has_change_permission': self.has_change_permission(request, obj),
            'has_delete_permission': self.has_delete_permission(request, obj),
            'has_file_field': True,
            'has_absolute_url': hasattr(self.model, 'get_absolute_url'),
            'ordered_objects': ordered_objects,
            'form_url': mark_safe(form_url),
            'opts': opts,
            'content_type_id': ContentType.objects.get_for_model(self.model).id,
            'save_as': self.save_as,
            'save_on_top': self.save_on_top,
            'root_path': self.admin_site.root_path,
            'onclick_attrib': (opts.get_ordered_objects() and change and 'onclick="submitOrderForm();"' or ''),
        })
        context_instance = template.RequestContext(request, current_app=self.admin_site.name)
        return render_to_response(self.change_form_template or [
            "admin/%s/%s/mass_change_form.html" % (app_label, opts.object_name.lower()),
            "admin/%s/mass_change_form.html" % app_label,
            "admin/mass_change_form.html"
        ], context, context_instance=context_instance)
                        		
    def mass_change_view(self, request, comma_separated_object_ids, extra_context=None):
        """The 'mass change' admin view for this model."""
        global new_object
        model = self.model
        opts = model._meta
                        		
        object_ids = comma_separated_object_ids.split(',')
        object_id = object_ids[0]

        try:
            obj = self.queryset(request).get(pk=unquote(object_id))
        except model.DoesNotExist:
            obj = None

        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        if obj is None:
            raise Http404(_('%(name)s object with primary key %(key)r does not exist.') % {'name': force_unicode(opts.verbose_name), 'key': escape(object_id)})

        if request.method == 'POST' and request.POST.has_key("_saveasnew"):
            return self.add_view(request, form_url='../add/')

        ModelForm = self.get_form(request, obj)
        formsets = []
        if request.method == 'POST':
            objects_count = 0
            changed_count = 0
            objects = self.queryset(request).filter(pk__in = object_ids)
            for obj in objects:
                objects_count += 1
                form = ModelForm(request.POST, request.FILES, instance=obj)
                                                				
                exclude = []
                for fieldname, field in form.fields.items():
                    mass_change_checkbox = '_mass_change_%s' % fieldname
                    if not (request.POST.has_key(mass_change_checkbox) and request.POST[mass_change_checkbox] == 'on'):
                        exclude.append(fieldname)
                for exclude_fieldname in exclude:
                    del form.fields[exclude_fieldname]
                                                				
                if form.is_valid():
                    form_validated = True
                    new_object = self.save_form(request, form, change=True)
                else:
                    form_validated = False
                    new_object = obj
                prefixes = {}
                for FormSet in self.get_formsets(request, new_object):
                    prefix = FormSet.get_default_prefix()
                    prefixes[prefix] = prefixes.get(prefix, 0) + 1
                    if prefixes[prefix] != 1:
                        prefix = "%s-%s" % (prefix, prefixes[prefix])
                    mass_change_checkbox = '_mass_change_%s' % prefix
                    if request.POST.has_key(mass_change_checkbox) and request.POST[mass_change_checkbox] == 'on':
                        formset = FormSet(request.POST, request.FILES, instance=new_object, prefix=prefix)
                        formsets.append(formset)
            	
                if all_valid(formsets) and form_validated:
                    self.admin_obj.save_model(request, new_object, form, change=True)
                    # self.save_model(request, new_object, form, change=True)
                    form.save_m2m()
                    for formset in formsets:
                        self.save_formset(request, form, formset, change=True)
                        		
                    change_message = self.construct_change_message(request, form, formsets)
                    self.log_change(request, new_object, change_message)
                    changed_count += 1
                                                            					
            if changed_count == objects_count:
                return self.response_change(request, new_object)
            else:
                raise Exception('Some of the selected objects could\'t be changed.')

        else:
            form = ModelForm(instance=obj)
            prefixes = {}
            for FormSet in self.get_formsets(request, obj):
                prefix = FormSet.get_default_prefix()
                prefixes[prefix] = prefixes.get(prefix, 0) + 1
                if prefixes[prefix] != 1:
                    prefix = "%s-%s" % (prefix, prefixes[prefix])
                formset = FormSet(instance=obj, prefix=prefix)
                formsets.append(formset)
            	
            adminForm = helpers.AdminForm(form, self.get_fieldsets(request, obj), self.prepopulated_fields)
            media = self.media + adminForm.media
            	
            inline_admin_formsets = []
            for inline, formset in zip(self.inline_instances, formsets):
                fieldsets = list(inline.get_fieldsets(request, obj))
                inline_admin_formset = helpers.InlineAdminFormSet(inline, formset, fieldsets)
                inline_admin_formsets.append(inline_admin_formset)
                media = media + inline_admin_formset.media
            	
            context = {
                'title': _('Change %s') % force_unicode(opts.verbose_name),
                'adminform': adminForm,
                'object_id': object_id,
                'original': obj,
                'is_popup': request.REQUEST.has_key('_popup'),
                'media': mark_safe(media),
                'inline_admin_formsets': inline_admin_formsets,
                'errors': helpers.AdminErrorList(form, formsets),
                'root_path': self.admin_site.root_path,
                'app_label': opts.app_label,
                'object_ids': comma_separated_object_ids,
            }
            context.update(extra_context or {})
            return self.render_mass_change_form(request, context, change=True, obj=obj)

    #noinspection PyRedeclaration
    mass_change_view = transaction.commit_on_success(mass_change_view)
