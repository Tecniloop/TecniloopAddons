###################################################################################
#
#    Copyright (C) 2020 Cetmix OÜ
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU LESSER GENERAL PUBLIC LICENSE as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###################################################################################

from datetime import datetime

from odoo.fields import Datetime

from .common import get_month


def _prepare_date_display(record, date):
    """
    Compose displayed date/time
    :param record: record
    :param datetime date: record date
    :return: (datetime or bool, date display string)
    """
    if not date:
        return False, ""
    now = Datetime.context_timestamp(record, Datetime.now())
    message_date = Datetime.context_timestamp(record, date)
    days_diff = (now.date() - message_date.date()).days
    date_format = datetime.strftime(message_date, "%H:%M")
    if days_diff == 0:
        date_display = date_format
    elif days_diff == 1:
        date_display = record.env._("Yesterday %s", date_format)
    elif now.year == message_date.year:
        date_display = record.env._("%(day)s %(month)s") % {
            "day": message_date.day,
            "month": get_month(record.env).get(message_date.month),
        }
    else:
        date_display = str(message_date.date())
    return message_date, date_display
